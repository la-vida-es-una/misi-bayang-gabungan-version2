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
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastmcp import FastMCP

from agent.coverage import (
    CoveragePlan,
    generate_coverage_plan,
    partition_plan,
    truncate_plan_for_battery,
)
from agent.pathfinder import straight_line_path
from world.engine import BATTERY_DRAIN_PER_MOVE, BATTERY_LOW_THRESHOLD, SCAN_RADIUS_CELLS, WorldEngine
from world.models import ZoneStatus

mcp = FastMCP(name="sar-swarm")

# Engine reference — injected at startup
_engine: WorldEngine | None = None

def init_mcp(engine: WorldEngine) -> None:
    global _engine
    _engine = engine


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


def _do_assign_drone_to_zone_with_plan(
    drone_id: str, zone_id: str, plan: CoveragePlan, full_plan_size: int | None = None
) -> dict[str, Any]:
    """Internal: assign a drone to a zone using a pre-computed coverage plan.

    This accepts an already-partitioned (or full) plan, handles battery
    truncation, approach path, and scan-queue setup.  Used by both the
    single-drone MCP tool and the fleet partitioning logic.
    """
    assert _engine is not None
    state = _engine.get_world_state()
    drone_state = state["drones"].get(drone_id)
    if drone_state is None:
        return {"ok": False, "error": f"Unknown drone: {drone_id}"}

    if plan.is_empty:
        return {"ok": False, "error": "No scan points in plan for this drone"}

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
    queue: list[tuple[list[tuple[int, int]], tuple[int, int]]] = []
    for i, sp in enumerate(safe_plan.scan_points):
        seg = safe_plan.segments[i] if i < len(safe_plan.segments) else []
        if i == 0:
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
        else:
            # Drone already at first scan point — inject synthetic arrival
            from world.models import DroneArrivedEvent

            _engine.inject_event(
                DroneArrivedEvent(
                    drone_id=drone_id,
                    col=drone_state["col"],
                    row=drone_state["row"],
                )
            )
        _engine.push_scan_queue_entry(drone_id, ([], first_scan_pt), front=True)

    total_moves = safe_plan.total_moves + len(approach)
    battery_cost = total_moves * BATTERY_DRAIN_PER_MOVE
    original_size = full_plan_size if full_plan_size is not None else len(plan.scan_points)
    return {
        "ok": True,
        "drone_id": drone_id,
        "zone_id": zone_id,
        "scan_points": len(safe_plan.scan_points),
        "total_moves": total_moves,
        "battery_cost_pct": round(battery_cost, 1),
        "truncated": len(safe_plan.scan_points) < original_size,
    }


def _do_assign_drone_to_zone(drone_id: str, zone_id: str) -> dict[str, Any]:
    """Internal: assign a single drone to a zone. Used by the MCP tool."""
    assert _engine is not None

    zone = _engine.grid.get_zone(zone_id)
    if zone is None:
        return {"ok": False, "error": f"Unknown zone: {zone_id}"}

    if zone.status == ZoneStatus.IDLE:
        _engine.start_scan([zone_id])
    elif zone.status == ZoneStatus.COMPLETED:
        return {"ok": False, "error": f"Zone {zone_id} already 100% covered"}

    if zone.fully_covered:
        return {"ok": False, "error": f"Zone {zone_id} fully covered"}

    plan = generate_coverage_plan(_engine.grid, zone_id, scan_radius=SCAN_RADIUS_CELLS)
    if plan.is_empty:
        return {"ok": False, "error": "No uncovered cells in zone"}

    return _do_assign_drone_to_zone_with_plan(drone_id, zone_id, plan, len(plan.scan_points))


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
    return _do_assign_drone_to_zone(drone_id, zone_id)


@mcp.tool()
def auto_assign_fleet() -> dict[str, Any]:
    """
    Automatically assign ALL idle drones to uncovered scanning zones.
    Distributes drones evenly across zones that still need coverage.
    All drones start moving simultaneously.

    Use this instead of calling assign_drone_to_zone repeatedly.
    This is the preferred way to deploy the fleet.
    """
    assert _engine is not None
    state = _engine.get_world_state()
    assignments = _engine.get_drone_assignments()

    # Find idle drones (not already assigned, not charging, have battery)
    idle_drones: list[str] = []
    low_battery: list[str] = []
    for did, d in state["drones"].items():
        if assignments.get(did) is not None:
            continue  # already assigned
        if d["status"] == "charging":
            continue
        if d["battery"] < BATTERY_LOW_THRESHOLD:
            low_battery.append(did)
            continue
        if d["path_remaining"] > 0:
            continue  # still moving
        idle_drones.append(did)

    if not idle_drones:
        return {
            "ok": True,
            "message": "No idle drones available",
            "low_battery": low_battery,
            "assigned": [],
        }

    # Find zones that need coverage
    zones_data = _engine.get_zones()
    target_zones: list[str] = []
    for zid, z in zones_data.items():
        if z.get("status") == "scanning" and z.get("coverage_ratio", 0) < 1.0:
            target_zones.append(zid)

    if not target_zones:
        return {
            "ok": True,
            "message": "No zones need coverage",
            "idle_drones": idle_drones,
            "assigned": [],
        }

    # Pass 1: Group idle drones by target zone (round-robin assignment)
    zone_drones: dict[str, list[str]] = {zid: [] for zid in target_zones}
    for i, did in enumerate(idle_drones):
        zid = target_zones[i % len(target_zones)]
        zone_drones[zid].append(did)

    # Pass 2: For each zone, generate ONE plan, partition among N drones
    results: list[dict[str, Any]] = []
    for zid, drones_for_zone in zone_drones.items():
        if not drones_for_zone:
            continue

        zone = _engine.grid.get_zone(zid)
        if zone is None:
            for did in drones_for_zone:
                results.append({"ok": False, "error": f"Unknown zone: {zid}"})
            continue

        if zone.status == ZoneStatus.IDLE:
            _engine.start_scan([zid])
        elif zone.status == ZoneStatus.COMPLETED:
            for did in drones_for_zone:
                results.append({"ok": False, "error": f"Zone {zid} already 100% covered"})
            continue

        if zone.fully_covered:
            for did in drones_for_zone:
                results.append({"ok": False, "error": f"Zone {zid} fully covered"})
            continue

        plan = generate_coverage_plan(_engine.grid, zid, scan_radius=SCAN_RADIUS_CELLS)
        if plan.is_empty:
            for did in drones_for_zone:
                results.append({"ok": False, "error": "No uncovered cells in zone"})
            continue

        full_plan_size = len(plan.scan_points)
        n = len(drones_for_zone)

        for idx, did in enumerate(drones_for_zone):
            part = partition_plan(plan, idx, n, grid=_engine.grid)
            result = _do_assign_drone_to_zone_with_plan(did, zid, part, full_plan_size)
            results.append(result)

    assigned = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]

    return {
        "ok": True,
        "assigned": assigned,
        "failed": failed,
        "low_battery": low_battery,
        "message": f"Assigned {len(assigned)} drones, {len(failed)} failed",
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


