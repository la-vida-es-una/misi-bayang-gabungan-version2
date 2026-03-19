"""
MCP Server — standardized tool interface between the Command Agent and drones.

ALL communication between the Agent (the LLM) and the Drones (the code) is
handled via these MCP tools.  The agent calls tools through the MCP protocol
(HTTP/SSE transport at /mcp) using langchain-mcp-adapters.

Tool set:
  Strategic (LLM decides):
    - list_drones()                     → dynamic fleet discovery
    - get_zones()                       → zone status and coverage
    - assign_drone_to_zone(d, z)        → generates coverage plan, queues scans
    - recall_drone(drone_id)            → return to base for charging
    - get_mission_status()              → compact overview with survivor counts

  Primitive (called by orchestrator's mechanical tier via MCP):
    - move_to(drone_id, x, y)           → move drone to cell
    - thermal_scan(drone_id)            → scan at current position
    - get_battery_status(drone_id)      → battery query

  Event polling:
    - get_pending_events()              → drain events since last poll
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict
from typing import Any

from fastmcp import FastMCP

from agent.coverage import (
    generate_coverage_plan,
    truncate_plan_for_battery,
)
from agent.pathfinder import straight_line_path
from world.engine import BATTERY_DRAIN_PER_MOVE, SCAN_RADIUS_CELLS, WorldEngine
from world.models import WorldEvent, ZoneStatus

mcp = FastMCP(name="sar-swarm")

# Engine reference — injected at startup
_engine: WorldEngine | None = None

# Per-MCP-consumer event queue (separate from the engine's per-consumer buffers)
_event_queue: deque[dict[str, Any]] = deque(maxlen=500)


def init_mcp(engine: WorldEngine) -> None:
    global _engine
    _engine = engine


def push_events(events: list[WorldEvent]) -> None:
    """Called by the world tick loop after each step()."""
    for e in events:
        _event_queue.append(asdict(e))  # type: ignore[arg-type]


# ── Strategic tools (LLM decides when to call) ──────────────────────────────


@mcp.tool()
def list_drones() -> dict[str, Any]:
    """
    Dynamically discover active drones on the network.
    Returns each drone's ID, battery %, status, position, and zone assignment.
    Agent must call this first — drone IDs are never hard-coded.
    """
    assert _engine is not None, "Engine not initialised"
    state = _engine.get_world_state()
    assignments = _engine.get_drone_assignments()
    drones = []
    for did, d in state["drones"].items():
        drones.append(
            {
                "id": did,
                "battery": round(d["battery"], 1),
                "status": d["status"],
                "pos": [d["col"], d["row"]],
                "path_remaining": d["path_remaining"],
                "assigned_zone": assignments.get(did),
                "scan_points_remaining": _engine.peek_scan_queue(did),
            }
        )
    return {"ok": True, "drones": drones, "count": len(drones)}


@mcp.tool()
def get_zones() -> dict[str, Any]:
    """
    Return all search zones with their status (idle/scanning/completed)
    and coverage ratios.
    """
    assert _engine is not None
    zones_data = _engine.get_zones()
    zones = []
    for zid, z in zones_data.items():
        zones.append(
            {
                "id": zid,
                "label": z.get("label", ""),
                "status": z.get("status", ""),
                "coverage_pct": round(z.get("coverage_ratio", 0) * 100, 1),
                "total_cells": z.get("total_cells", 0),
            }
        )
    return {"ok": True, "zones": zones, "count": len(zones)}


@mcp.tool()
def assign_drone_to_zone(drone_id: str, zone_id: str) -> dict[str, Any]:
    """
    Assign a drone to systematically cover a zone using a boustrophedon
    (lawn-mower) pattern.  Generates an optimal coverage plan with scan
    waypoints.  The drone moves to each scan point and thermal_scan() is
    called at each one via MCP.

    Args:
        drone_id: ID of the drone to assign.
        zone_id: ID of the zone to cover.
    """
    assert _engine is not None
    state = _engine.get_world_state()
    drone_state = state["drones"].get(drone_id)
    if drone_state is None:
        return {"ok": False, "error": f"Unknown drone: {drone_id}"}

    zone = _engine.grid.get_zone(zone_id)
    if zone is None:
        return {"ok": False, "error": f"Unknown zone: {zone_id}"}

    if zone.status == ZoneStatus.IDLE:
        _engine.start_scan([zone_id])
    elif zone.status == ZoneStatus.COMPLETED:
        return {"ok": False, "error": f"Zone {zone_id} already 100% covered"}

    if zone.fully_covered:
        return {"ok": False, "error": f"Zone {zone_id} fully covered"}

    # Generate coverage plan
    plan = generate_coverage_plan(_engine.grid, zone_id, scan_radius=SCAN_RADIUS_CELLS)
    if plan.is_empty:
        return {"ok": False, "error": "No uncovered cells in zone"}

    # Truncate plan for battery
    drone_pos = (drone_state["col"], drone_state["row"])
    safe_plan = truncate_plan_for_battery(
        plan,
        drone_battery=drone_state["battery"],
        drone_pos=drone_pos,
        base_pos=(_engine.base_col, _engine.base_row),
    )
    if safe_plan.is_empty:
        return {
            "ok": False,
            "error": f"Battery too low ({drone_state['battery']:.0f}%). "
            "Recall for charging first.",
        }

    # Build approach path from drone to first scan point
    first_sp = safe_plan.scan_points[0]
    approach = straight_line_path(
        drone_state["col"], drone_state["row"], first_sp[0], first_sp[1]
    )

    # Build scan queue: list of (segment, scan_point) pairs
    # First entry: approach + first segment → first scan point
    queue: list[tuple[list[tuple[int, int]], tuple[int, int]]] = []
    for i, sp in enumerate(safe_plan.scan_points):
        seg = safe_plan.segments[i] if i < len(safe_plan.segments) else []
        if i == 0:
            # Prepend approach to the first segment
            seg = approach + seg
        queue.append((seg, sp))

    # Store zone assignment and scan queue
    _engine.set_drone_zone(drone_id, zone_id)
    _engine.set_scan_queue(drone_id, queue)

    # Start the drone moving: pop first entry, assign its segment
    first_entry = _engine.pop_scan_queue(drone_id)
    if first_entry:
        first_seg, first_scan_pt = first_entry
        if first_seg:
            _engine.assign_path(drone_id, first_seg)
        # Re-insert just the scan point (segment consumed, scan still pending)
        _engine._lock.acquire()
        try:
            q = _engine._drone_scan_queue.setdefault(drone_id, [])
            q.insert(0, ([], first_scan_pt))
        finally:
            _engine._lock.release()

    total_moves = safe_plan.total_moves + len(approach)
    battery_cost = total_moves * BATTERY_DRAIN_PER_MOVE
    return {
        "ok": True,
        "drone_id": drone_id,
        "zone_id": zone_id,
        "scan_points": len(safe_plan.scan_points),
        "total_moves": total_moves,
        "battery_cost_pct": round(battery_cost, 1),
        "truncated": len(safe_plan.scan_points) < len(plan.scan_points),
    }


@mcp.tool()
def recall_drone(drone_id: str) -> dict[str, Any]:
    """
    Recall a drone to base for charging.  Clears current zone assignment,
    scan queue, and path.  Generates a return path.

    Args:
        drone_id: ID of the drone to recall.
    """
    assert _engine is not None
    return _engine.recall_drone(drone_id)


@mcp.tool()
def get_mission_status() -> dict[str, Any]:
    """
    Compact mission overview: zone coverages, drone statuses, survivor
    detection progress, and whether all zones are 100% covered.
    """
    assert _engine is not None
    zones_data = _engine.get_zones()
    state = _engine.get_world_state()
    assignments = _engine.get_drone_assignments()
    found, total = _engine.get_survivor_counts()

    zone_summary = {}
    for zid, z in zones_data.items():
        zone_summary[zid] = {
            "coverage_pct": round(z.get("coverage_ratio", 0) * 100, 1),
            "status": z.get("status", ""),
        }

    all_covered = (
        all(z.get("coverage_ratio", 0) >= 1.0 for z in zones_data.values())
        if zones_data
        else False
    )

    drones = []
    for did, d in state["drones"].items():
        drones.append(
            {
                "id": did,
                "battery": round(d["battery"], 1),
                "status": d["status"],
                "zone": assignments.get(did),
            }
        )

    return {
        "ok": True,
        "tick": state["tick"],
        "zones": zone_summary,
        "all_zones_covered": all_covered,
        "survivors_found": found,
        "survivors_total": total,
        "drones": drones,
    }


# ── Primitive tools (called by orchestrator mechanical tier via MCP) ─────────


@mcp.tool()
def move_to(drone_id: str, x: int, y: int) -> dict[str, Any]:
    """
    Move drone to cell (x, y).  Generates a straight-line path and queues it.
    The world engine walks the path one cell per tick.

    Args:
        drone_id: ID of the drone to move.
        x: Target column (cell address).
        y: Target row (cell address).
    """
    assert _engine is not None
    state = _engine.get_world_state()
    drone_state = state["drones"].get(drone_id)
    if drone_state is None:
        return {"ok": False, "error": f"Unknown drone: {drone_id}"}

    path = straight_line_path(drone_state["col"], drone_state["row"], x, y)
    events = _engine.assign_path(drone_id, path)
    push_events(events)

    rejected = [
        asdict(e)  # type: ignore[arg-type]
        for e in events
        if getattr(e, "type", None) == "out_of_bounds_rejected"
    ]
    if rejected:
        return {"ok": False, "error": "target out of bounds", "rejected": rejected}

    return {
        "ok": True,
        "drone_id": drone_id,
        "target": {"x": x, "y": y},
        "path_length": len(path),
    }


@mcp.tool()
def thermal_scan(drone_id: str) -> dict[str, Any]:
    """
    Activate thermal sensor on drone.  Detects survivors within scan radius
    and marks zone cells as covered.  Must be called at each scan waypoint
    for zone coverage to progress.

    Args:
        drone_id: ID of the scanning drone.
    """
    assert _engine is not None
    events = _engine.thermal_scan(drone_id)
    push_events(events)
    found = [
        asdict(e)  # type: ignore[arg-type]
        for e in events
        if getattr(e, "type", None) == "survivor_found"
    ]
    zone_covered = [
        asdict(e)  # type: ignore[arg-type]
        for e in events
        if getattr(e, "type", None) == "zone_covered"
    ]
    return {
        "ok": True,
        "drone_id": drone_id,
        "survivors_found": len(found),
        "zones_completed": [e.get("zone_id") for e in zone_covered],
        "events": found,
    }


@mcp.tool()
def get_battery_status(drone_id: str) -> dict[str, Any]:
    """
    Return current battery level for a drone.

    Args:
        drone_id: ID of the drone to query.
    """
    assert _engine is not None
    battery = _engine.get_battery(drone_id)
    if battery is None:
        return {"ok": False, "error": f"Unknown drone: {drone_id}"}
    return {"ok": True, "drone_id": drone_id, "battery": round(battery, 2)}


# ── Event polling ─────────────────────────────────────────────────────────────


@mcp.tool()
def get_pending_events() -> dict[str, Any]:
    """
    Return and clear all world events queued since last poll.
    The agent polls this to detect: drone_arrived, battery_low,
    survivor_found, zone_covered, scan_started, drone_charging.
    """
    events = list(_event_queue)
    _event_queue.clear()
    return {"ok": True, "events": events, "count": len(events)}
