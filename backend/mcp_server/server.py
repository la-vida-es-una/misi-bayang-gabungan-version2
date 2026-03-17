"""
MCP Server — stateless adapter between the LLM agent and the World Engine.

Frozen tool contracts (must not be renamed or re-signatured):
  - move_to(drone_id, x, y)        → queues path to (x,y)
  - get_battery_status(drone_id)   → returns battery %
  - thermal_scan(drone_id)         → detects survivors near drone

Additional tools (evolvable):
  - get_world_state()              → full snapshot
  - list_drones()                  → dynamic fleet discovery
  - get_pending_events()           → event queue since last poll
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict
from typing import Any

from fastmcp import FastMCP

from world.engine import WorldEngine
from world.models import WorldEvent

# ── Path planner import (Layer 2 — lightweight, no LLM) ─────────────────────
from agent.pathfinder import straight_line_path

mcp = FastMCP(name="sar-swarm")

# Engine reference injected at startup (see main.py)
_engine: WorldEngine | None = None
_event_queue: deque[dict[str, Any]] = deque(maxlen=500)
_queue_lock = asyncio.Lock()


def init_mcp(engine: WorldEngine) -> None:
    global _engine
    _engine = engine


def push_events(events: list[WorldEvent]) -> None:
    """Called by the world tick loop after each step()."""
    for e in events:
        _event_queue.append(
            asdict(e)
        )  # dataclass → dict; avoids .get() on typed instances


# ── Frozen tools ─────────────────────────────────────────────────────────────


@mcp.tool()
def move_to(drone_id: str, x: int, y: int) -> dict[str, Any]:
    """
    Move drone to cell (x, y). Internally resolves to a straight-line path
    queued on the drone; the world engine walks it one cell per tick.
    Rejects out-of-polygon targets and returns an error event.

    Args:
        drone_id: ID of the drone to move.
        x: Target column (cell address).
        y: Target row (cell address).
    """
    assert _engine is not None, "Engine not initialised"
    state = _engine.get_world_state()
    drone_state = state["drones"].get(drone_id)
    if drone_state is None:
        return {"ok": False, "error": f"Unknown drone: {drone_id}"}

    path = straight_line_path(drone_state["col"], drone_state["row"], x, y)
    events = _engine.assign_path(drone_id, path)
    push_events(events)

    rejected = [
        e for e in asdict_list(events) if e.get("type") == "out_of_bounds_rejected"
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
    Activate thermal sensor on drone. Detects survivors within scan radius.
    Transitions found survivors from 'missing' to 'found'.

    Args:
        drone_id: ID of the scanning drone.
    """
    assert _engine is not None
    events = _engine.thermal_scan(drone_id)
    push_events(events)
    found = [e for e in asdict_list(events) if e.get("type") == "survivor_found"]
    return {
        "ok": True,
        "drone_id": drone_id,
        "survivors_found": len(found),
        "events": found,
    }


# ── Evolvable tools ───────────────────────────────────────────────────────────


@mcp.tool()
def get_world_state() -> dict[str, Any]:
    """Return a full snapshot of world state: drones, survivors, grid, tick."""
    assert _engine is not None
    return _engine.get_world_state()


@mcp.tool()
def list_drones() -> dict[str, Any]:
    """
    Dynamically discover active drones. Agent must call this first;
    drone IDs are never hard-coded in the agent.
    """
    assert _engine is not None
    ids = _engine.list_drone_ids()
    return {"ok": True, "drone_ids": ids, "count": len(ids)}


@mcp.tool()
def get_pending_events() -> dict[str, Any]:
    """
    Return and clear all events queued since last poll.
    Agent polls this each reasoning cycle to detect: battery low,
    survivor found, drone arrived, out-of-bounds rejections.
    """
    events = list(_event_queue)
    _event_queue.clear()
    return {"ok": True, "events": events, "count": len(events)}


# ── Helper ────────────────────────────────────────────────────────────────────


def asdict_list(events: list[WorldEvent]) -> list[dict[str, Any]]:
    """Convert a list of WorldEvent dataclasses to plain dicts."""
    return [asdict(e) for e in events]  # type: ignore[arg-type]
