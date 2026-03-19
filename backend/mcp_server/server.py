"""
MCP Server — standardized tool interface between agents and the World Engine.

This server exposes drone control functions as MCP tools, fulfilling the
study case requirement that "all communication between the Agent (the LLM)
and the Drones (the code) must be handled via the Model Context Protocol."

The same tools are available:
  1. As MCP tools at /mcp (for external MCP clients)
  2. As LangChain @tool functions in the orchestrator (for in-process agent)

Both call the same WorldEngine methods, ensuring consistent behavior.

Tool set (strategic level):
  - list_drones()                    → dynamic fleet discovery
  - get_zones()                      → zone status and coverage
  - assign_drone_to_zone(d, z)       → coverage path + auto-scan
  - recall_drone(drone_id)           → return to base for charging
  - get_mission_status()             → compact overview
  - get_battery_status(drone_id)     → battery query
  - thermal_scan(drone_id)           → manual scan (fallback)
  - move_to(drone_id, x, y)         → manual move (fallback)
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict
from typing import Any

from fastmcp import FastMCP

from agent.coverage import generate_coverage_path, truncate_for_battery
from agent.pathfinder import straight_line_path
from world.engine import BATTERY_DRAIN_PER_MOVE, SCAN_RADIUS_CELLS, WorldEngine
from world.models import WorldEvent, ZoneStatus

mcp = FastMCP(name="sar-swarm")

# Engine reference injected at startup
_engine: WorldEngine | None = None
_event_queue: deque[dict[str, Any]] = deque(maxlen=500)
_queue_lock = asyncio.Lock()


def init_mcp(engine: WorldEngine) -> None:
    global _engine
    _engine = engine


def push_events(events: list[WorldEvent]) -> None:
    """Called by the world tick loop after each step()."""
    for e in events:
        _event_queue.append(asdict(e))  # type: ignore[arg-type]


# ── Strategic tools (primary) ────────────────────────────────────────────────


@mcp.tool()
def list_drones() -> dict[str, Any]:
    """
    Dynamically discover active drones. Returns each drone's ID, battery %,
    status, position, and current zone assignment.
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
    Assign a drone to systematically cover a zone. Generates an optimal
    boustrophedon (lawn-mower) coverage path automatically and enables
    auto-scanning. The drone will cover the zone without further commands.

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

    coverage_path = generate_coverage_path(
        _engine.grid, zone_id, scan_radius=SCAN_RADIUS_CELLS
    )
    if not coverage_path:
        return {"ok": False, "error": "No uncovered cells in zone"}

    approach = straight_line_path(
        drone_state["col"],
        drone_state["row"],
        coverage_path[0][0],
        coverage_path[0][1],
    )
    full_path = approach + coverage_path

    safe_path = truncate_for_battery(
        full_path,
        drone_battery=drone_state["battery"],
        base_pos=(_engine.base_col, _engine.base_row),
    )
    if not safe_path:
        return {
            "ok": False,
            "error": f"Battery too low ({drone_state['battery']:.0f}%)",
        }

    result = _engine.assign_coverage(drone_id, safe_path, zone_id)
    if not result.get("ok"):
        return result

    cost = len(safe_path) * BATTERY_DRAIN_PER_MOVE
    return {
        "ok": True,
        "drone_id": drone_id,
        "zone_id": zone_id,
        "waypoints": result["waypoints"],
        "battery_cost_pct": round(cost, 1),
        "truncated": len(safe_path) < len(full_path),
    }


@mcp.tool()
def recall_drone(drone_id: str) -> dict[str, Any]:
    """
    Recall a drone to base for charging. Clears current assignment
    and generates a return path.

    Args:
        drone_id: ID of the drone to recall.
    """
    assert _engine is not None
    return _engine.recall_drone(drone_id)


@mcp.tool()
def get_mission_status() -> dict[str, Any]:
    """
    Compact mission overview: zone coverages, drone statuses, and
    whether all zones are 100% covered.
    """
    assert _engine is not None
    zones_data = _engine.get_zones()
    state = _engine.get_world_state()
    assignments = _engine.get_drone_assignments()

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
        "drones": drones,
    }


# ── Fallback tools (manual control) ──────────────────────────────────────────


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


@mcp.tool()
def thermal_scan(drone_id: str) -> dict[str, Any]:
    """
    Manually activate thermal sensor on drone. Detects survivors within
    scan radius. Usually not needed — auto-scanning handles this during
    coverage flights.

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
    return {
        "ok": True,
        "drone_id": drone_id,
        "survivors_found": len(found),
        "events": found,
    }


@mcp.tool()
def move_to(drone_id: str, x: int, y: int) -> dict[str, Any]:
    """
    Manually move drone to cell (x, y). Generates a straight-line path.
    Usually not needed — assign_drone_to_zone handles coverage automatically.

    Args:
        drone_id: ID of the drone to move.
        x: Target column.
        y: Target row.
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


# ── Helper ────────────────────────────────────────────────────────────────────


def asdict_list(events: list[WorldEvent]) -> list[dict[str, Any]]:
    return [asdict(e) for e in events]  # type: ignore[arg-type]
