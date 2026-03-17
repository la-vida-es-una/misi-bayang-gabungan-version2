"""
Mission Receiver — full lifecycle REST + SSE.

Lifecycle endpoints:
  POST /mission/define_map          — master polygon + drone count + survivor count
  POST /mission/start               — draw zone 1 then start
  POST /mission/zone/add            — add next zone (only valid while PAUSED)
  POST /mission/resume              — resume after zone added
  POST /mission/end                 — permanently end
  GET  /mission/state               — snapshot
  GET  /mission/stream              — SSE stream (all events + tick snapshots)

Coordinate convention:
  Frontend sends [lat, lon]. This file flips to [lon, lat] before any
  geo/grid operation. Everything below this boundary is [lon, lat].
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from dataclasses import asdict
from typing import Any

# from typing import AsyncGenerator
# Basedpyright Diagnostics:
# 1. This type is deprecated as of Python 3.9; use "collections.abc.AsyncGenerator" instead [reportDeprecated]
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from world.engine import WorldEngine
from world.grid import Grid
from world.models import MissionPhase, WorldEvent

router = APIRouter(prefix="/mission")

# ── Singleton mission state ───────────────────────────────────────────────────
# Only one active mission at a time (hackathon scope).

_state: dict[str, Any] = {
    "engine": None,  # WorldEngine | None
    "grid": None,  # Grid | None
    "phase": MissionPhase.PENDING,
    "mission_id": None,
    "tick_task": None,
    "agent_task": None,
}

# SSE broadcast queue — all subscribers share the same events
_sse_queues: list[asyncio.Queue[str]] = []

WORLD_TICK_INTERVAL = 0.5  # seconds — separate from agent tick


# ── Pydantic request models ───────────────────────────────────────────────────


class LatLon(BaseModel):
    lat: float
    lon: float


class DefineMissionRequest(BaseModel):
    """Step 1: define master map."""

    # geojson_polygon coords as [[lat, lon], ...] — flipped internally
    geojson_polygon: dict[str, Any]
    drone_ids: list[str]  # e.g. ["drone_1","drone_2","drone_3"]
    survivor_count: int = 5  # how many survivors to auto-seed
    base: LatLon | None = None  # optional explicit base; default = first in-bounds cell
    cell_size_m: float = 1.0


class ZoneRequest(BaseModel):
    """A drawable search zone polygon."""

    geojson_polygon: dict[str, Any]  # [[lat, lon], ...] — flipped internally


class StartRequest(BaseModel):
    """Step 2: provide zone 1 and start mission."""

    zone: ZoneRequest
    mission_text: str = "Scan the zone for survivors."


# ── Coordinate flip helpers ───────────────────────────────────────────────────


def _flip_polygon(geojson: dict[str, Any]) -> dict[str, Any]:
    """
    Flip all coordinate pairs [lat, lon] → [lon, lat] inside a GeoJSON Polygon.
    Handles both Polygon and wrapped {"type":"Polygon","coordinates":...} forms.
    """
    coords = geojson.get("coordinates", [])
    flipped_rings = []
    for ring in coords:
        flipped_rings.append([[pt[1], pt[0]] for pt in ring])
    return {"type": "Polygon", "coordinates": flipped_rings}


def _flip_latlon(lat: float, lon: float) -> tuple[float, float]:
    """Returns (lon, lat) — GeoJSON order."""
    return lon, lat


# ── SSE helpers ───────────────────────────────────────────────────────────────


def _broadcast(event_type: str, data: dict[str, Any]) -> None:
    payload = json.dumps({"event": event_type, "data": data})
    for q in _sse_queues:
        q.put_nowait(payload)


def _broadcast_events(events: list[WorldEvent]) -> None:
    for e in events:
        d = asdict(e)  # type: ignore[arg-type]
        _broadcast(d.get("type", "unknown"), d)


async def _sse_generator(queue: asyncio.Queue[str]) -> AsyncGenerator[str, None]:
    try:
        while True:
            payload = await queue.get()
            yield f"data: {payload}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        _sse_queues.remove(queue)


# ── Background loops ──────────────────────────────────────────────────────────


async def _world_tick_loop(engine: WorldEngine) -> None:
    while True:
        events = engine.step()
        if events:
            _broadcast_events(events)
            # Also push to MCP event queue
            from mcp_server.server import push_events

            push_events(events)
        # Broadcast tick snapshot regardless (frontend uses for live positions)
        _broadcast("tick", engine.get_world_state())
        await asyncio.sleep(WORLD_TICK_INTERVAL)


async def _agent_loop(mission_text: str, base_col: int, base_row: int) -> None:
    from agent.orchestrator import CommandAgent

    agent = CommandAgent(mission_text, base_col, base_row)
    await agent.run()


# ── Survivor auto-seed ────────────────────────────────────────────────────────


def _seed_survivors(
    engine: WorldEngine, grid: Grid, count: int
) -> list[dict[str, Any]]:
    """Randomly place `count` survivors in in-bounds cells, avoiding base."""
    all_cells = [
        (c, r)
        for r in range(grid.rows)
        for c in range(grid.cols)
        if grid.in_bounds(c, r) and not (c == engine.base_col and r == engine.base_row)
    ]
    chosen = random.sample(all_cells, min(count, len(all_cells)))
    seeded = []
    for i, (col, row) in enumerate(chosen):
        sid = f"survivor_{i + 1}"
        engine.add_survivor(sid, col, row)
        lon, lat = grid.cell_to_geo(col, row)
        seeded.append({"id": sid, "lat": lat, "lon": lon, "status": "missing"})
    return seeded


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/define_map")
async def define_map(req: DefineMissionRequest) -> dict[str, Any]:
    """
    Step 1 — Define master map, drones, base, survivors.
    Does NOT start the mission. Returns grid info for frontend to render.
    """
    if not req.drone_ids:
        raise HTTPException(400, "At least one drone required")
    if len(req.drone_ids) > 5:
        raise HTTPException(400, "Maximum 5 drones")

    flipped_polygon = _flip_polygon(req.geojson_polygon)
    grid = Grid(flipped_polygon, cell_size_m=req.cell_size_m)

    # Resolve base
    if req.base:
        b_lon, b_lat = _flip_latlon(req.base.lat, req.base.lon)
        base_col, base_row = grid.geo_to_cell(b_lon, b_lat)
        if not grid.in_bounds(base_col, base_row):
            raise HTTPException(400, "Base location is outside the map polygon")
    else:
        base_col, base_row = _find_first_cell(grid)

    engine = WorldEngine(grid=grid, base_col=base_col, base_row=base_row)
    for drone_id in req.drone_ids:
        engine.add_drone(drone_id)

    survivors = _seed_survivors(engine, grid, req.survivor_count)

    # Register with MCP server
    from mcp_server.server import init_mcp

    init_mcp(engine)

    mission_id = str(uuid.uuid4())[:8]
    _state.update(
        {
            "engine": engine,
            "grid": grid,
            "phase": MissionPhase.PENDING,
            "mission_id": mission_id,
        }
    )

    b_lon_out, b_lat_out = grid.cell_to_geo(base_col, base_row)
    return {
        "mission_id": mission_id,
        "grid_bounds": grid.bounds,
        "base": {"col": base_col, "row": base_row, "lat": b_lat_out, "lon": b_lon_out},
        "drone_ids": req.drone_ids,
        "survivors": survivors,
    }


@router.post("/start")
async def start_mission(req: StartRequest) -> dict[str, Any]:
    """
    Step 2 — Set zone 1 and start mission.
    Must call /define_map first.
    """
    engine: WorldEngine | None = _state.get("engine")
    grid: Grid | None = _state.get("grid")
    if engine is None or grid is None:
        raise HTTPException(400, "Call /define_map first")
    if _state["phase"] not in (MissionPhase.PENDING,):
        raise HTTPException(400, f"Cannot start from phase: {_state['phase']}")

    flipped = _flip_polygon(req.zone.geojson_polygon)
    zone_info = grid.set_zone(flipped)

    events = engine.start()
    _broadcast_events(events)

    loop = asyncio.get_event_loop()
    _state["tick_task"] = loop.create_task(_world_tick_loop(engine))
    _state["agent_task"] = loop.create_task(
        _agent_loop(req.mission_text, engine.base_col, engine.base_row)
    )
    _state["phase"] = MissionPhase.RUNNING

    return {"ok": True, "zone": zone_info, "phase": "running"}


@router.post("/zone/add")
async def add_zone(req: ZoneRequest) -> dict[str, Any]:
    """
    Add next search zone. Only valid while PAUSED.
    Does NOT resume — call /resume after this.
    """
    engine: WorldEngine | None = _state.get("engine")
    grid: Grid | None = _state.get("grid")
    if engine is None or grid is None:
        raise HTTPException(400, "No active mission")
    if engine.phase != MissionPhase.PAUSED:
        raise HTTPException(
            400, f"Can only add zone while PAUSED, current: {engine.phase.value}"
        )

    flipped = _flip_polygon(req.geojson_polygon)
    zone_info = grid.set_zone(flipped)

    return {"ok": True, "zone": zone_info}


@router.post("/resume")
async def resume_mission() -> dict[str, Any]:
    """Resume after a zone has been added via /zone/add."""
    engine: WorldEngine | None = _state.get("engine")
    if engine is None:
        raise HTTPException(400, "No active mission")
    if engine.phase != MissionPhase.PAUSED:
        raise HTTPException(400, f"Not paused, current: {engine.phase.value}")

    events = engine.start()  # start() handles PAUSED → RUNNING
    _broadcast_events(events)
    _state["phase"] = MissionPhase.RUNNING

    return {"ok": True, "phase": "running"}


@router.post("/end")
async def end_mission() -> dict[str, Any]:
    """Permanently end the mission."""
    engine: WorldEngine | None = _state.get("engine")
    if engine is None:
        raise HTTPException(400, "No active mission")

    events = engine.end()
    _broadcast_events(events)
    _state["phase"] = MissionPhase.ENDED

    # Cancel background tasks
    for key in ("tick_task", "agent_task"):
        task = _state.get(key)
        if task and not task.done():
            task.cancel()

    return {"ok": True, "phase": "ended"}


@router.get("/state")
async def get_state() -> dict[str, Any]:
    engine: WorldEngine | None = _state.get("engine")
    if engine is None:
        raise HTTPException(404, "No active mission")
    return engine.get_world_state()


@router.get("/stream")
async def stream_events() -> StreamingResponse:
    """
    SSE stream. Connect once; receive all world events + every tick snapshot.

    Event format:
      data: {"event": "<type>", "data": {...}}\n\n

    Event types:
      tick              — full world snapshot every WORLD_TICK_INTERVAL seconds
      drone_moved       — drone advanced one cell
      drone_arrived     — drone reached end of path
      drone_charging    — drone charging at base
      battery_low       — drone battery ≤ 25%
      survivor_found    — survivor status → found
      zone_covered      — all zone cells scanned
      mission_paused    — auto-pause triggered
      mission_resumed   — mission resumed
      mission_ended     — mission permanently ended
      out_of_bounds_rejected — move_to target rejected
    """
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
    _sse_queues.append(queue)
    return StreamingResponse(
        _sse_generator(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _find_first_cell(grid: Grid) -> tuple[int, int]:
    for r in range(grid.rows):
        for c in range(grid.cols):
            if grid.in_bounds(c, r):
                return c, r
    raise ValueError("No in-bounds cells in grid")
