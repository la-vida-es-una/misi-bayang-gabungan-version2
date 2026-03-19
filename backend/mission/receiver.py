"""
Mission Receiver — full lifecycle REST + SSE.

Lifecycle endpoints:
  POST /mission/define_map          — master polygon + drone count + survivor count
  POST /mission/start               — start world tick loop + agent loop
  POST /mission/end                 — permanently end

Zone endpoints:
  POST /mission/zone/add            — register a new search zone
  POST /mission/zone/remove         — remove a zone
  POST /mission/zone/scan           — start scanning selected zones
  POST /mission/zone/stop           — stop scanning selected zones

Agent endpoints:
  POST /mission/agent/stop          — pause the AI agent loop
  POST /mission/agent/resume        — resume the AI agent loop
  POST /mission/agent/prompt        — inject user message into agent

Query endpoints:
  GET  /mission/state               — snapshot
  GET  /mission/stream              — SSE stream (all events + tick snapshots)

Coordinate convention:
  Frontend sends [lat, lon]. This file flips to [lon, lat] before any
  geo/grid operation. Everything below this boundary is [lon, lat].
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import traceback
import uuid
from dataclasses import asdict
from typing import Any

from collections.abc import AsyncGenerator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from world.engine import WorldEngine
from world.grid import Grid
from world.models import AgentErrorEvent, MissionPhase, WorldEvent

logger = logging.getLogger("sar.receiver")

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
    "agent": None,  # CommandAgent | None
}

# SSE broadcast queue — all subscribers share the same events
_sse_queues: list[asyncio.Queue[str]] = []

WORLD_TICK_INTERVAL = 1.0  # seconds — synced closer to agent tick for smoother movement


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
    cell_size_m: float = 0.0  # 0 = auto-calculate from polygon size (recommended)


class ZoneAddRequest(BaseModel):
    """Add a new search zone polygon."""

    geojson_polygon: dict[str, Any]  # [[lat, lon], ...] — flipped internally
    label: str | None = None  # optional custom label; auto-generated if None


class ZoneRemoveRequest(BaseModel):
    """Remove a zone by ID."""

    zone_id: str


class ZoneScanRequest(BaseModel):
    """Start or stop scanning selected zones."""

    zone_ids: list[str]


class StartRequest(BaseModel):
    """Start the mission (world ticks + agent). No zone required at start."""

    mission_text: str = "Scan the zone for survivors."


class AgentPromptRequest(BaseModel):
    """Inject a user message into the agent."""

    message: str


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
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # slow client — drop event rather than crash broadcast


def _broadcast_events(events: list[WorldEvent]) -> None:
    for e in events:
        d = asdict(e)  # type: ignore[arg-type]
        _broadcast(d.get("type", "unknown"), d)


def broadcast_event(event: WorldEvent) -> None:
    """Public helper for other modules (e.g. agent) to broadcast events."""
    d = asdict(event)  # type: ignore[arg-type]
    _broadcast(d.get("type", "unknown"), d)


async def _sse_generator(queue: asyncio.Queue[str]) -> AsyncGenerator[str, None]:
    try:
        while True:
            payload = await queue.get()
            yield f"data: {payload}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        try:
            _sse_queues.remove(queue)
        except ValueError:
            pass  # already removed


# ── Background loops ──────────────────────────────────────────────────────────


async def _world_tick_loop(engine: WorldEngine) -> None:
    while True:
        try:
            events = engine.step()
            if events:
                _broadcast_events(events)
                # Also push to MCP event queue
                from mcp_server.server import push_events

                push_events(events)
            # Broadcast tick snapshot regardless (frontend uses for live positions)
            _broadcast("tick", engine.get_world_state())
        except Exception:
            tb = traceback.format_exc()
            logger.error("World tick loop error:\n%s", tb)
            # Broadcast error to frontend so it's not silent
            broadcast_event(
                AgentErrorEvent(tick=0, error="World tick loop error", detail=tb)
            )
        await asyncio.sleep(WORLD_TICK_INTERVAL)


async def _agent_loop(
    engine: WorldEngine, mission_text: str, base_col: int, base_row: int
) -> None:
    try:
        from agent.orchestrator import CommandAgent

        logger.info("Starting strategic command agent")
        agent = CommandAgent(engine, mission_text, base_col, base_row)

        _state["agent"] = agent
        await agent.run()
    except Exception:
        tb = traceback.format_exc()
        logger.error("Agent loop crashed:\n%s", tb)
        broadcast_event(AgentErrorEvent(tick=0, error="Agent loop crashed", detail=tb))


# ── Cell size helper ─────────────────────────────────────────────────────────


def _resolve_cell_size(flipped_polygon: dict[str, Any], requested: float) -> float:
    """
    Determine a sensible cell size in polygon coordinate units.

    If `requested` is 0 (auto), the cell size is computed so that the
    longer polygon dimension is divided into ~100 cells — giving a
    manageable grid regardless of whether coords are degrees or metres.

    If `requested` > 0 it is used directly (test/manual override).
    The only guard is that it must not produce a zero-dimension grid:
    if the polygon is smaller than one cell in both dimensions, we
    fall back to auto.
    """
    if requested > 0:
        from shapely.geometry import shape as _shape

        poly = _shape(flipped_polygon)
        minx, miny, maxx, maxy = poly.bounds
        width = maxx - minx
        height = maxy - miny
        # If requested cell is larger than the polygon, fall through to auto
        if width >= requested or height >= requested:
            return requested

    # Auto: target ~100 cells along the longer side
    from shapely.geometry import shape as _shape

    poly = _shape(flipped_polygon)
    minx, miny, maxx, maxy = poly.bounds
    longer = max(maxx - minx, maxy - miny)
    if longer <= 0:
        return 1.0  # degenerate polygon, will be caught later
    return longer / 25.0  # Simpler coordinates (0-25) for local LLM


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
    cell_size = _resolve_cell_size(flipped_polygon, req.cell_size_m)
    grid = Grid(flipped_polygon, cell_size_m=cell_size)

    # Resolve base
    if req.base:
        b_lon, b_lat = _flip_latlon(req.base.lat, req.base.lon)
        base_col, base_row = grid.geo_to_cell(b_lon, b_lat)
        # Clamp to valid grid bounds — a user-placed base slightly outside
        # the computed cell range is snapped to nearest valid cell
        base_col = max(0, min(base_col, grid.cols - 1))
        base_row = max(0, min(base_row, grid.rows - 1))
        if not grid.in_bounds(base_col, base_row):
            # Snap to first in-bounds cell as fallback
            base_col, base_row = _find_first_cell(grid)
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
            "agent": None,
            "master_polygon": flipped_polygon,  # Store for auto-zone creation
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
    Start the mission — begin world ticks + agent loop.
    No zone required at start. Zones can be added/scanned any time while running.
    Must call /define_map first.
    """
    engine: WorldEngine | None = _state.get("engine")
    if engine is None:
        raise HTTPException(400, "Call /define_map first")
    if _state["phase"] != MissionPhase.PENDING:
        raise HTTPException(400, f"Cannot start from phase: {_state['phase']}")

    events = engine.start()
    _broadcast_events(events)

    # Auto-create and start default zone if none exist
    if not engine.get_zones():
        master_poly = _state.get("master_polygon")
        if master_poly:
            zone_events = engine.add_zone(
                "default_zone", master_poly, label="Search Area"
            )
            _broadcast_events(zone_events)
            scan_events = engine.start_scan(["default_zone"])
            _broadcast_events(scan_events)
            logger.info("Auto-created and started default_zone from master polygon")
    else:
        # Zones exist - start scanning all existing zones
        existing_zones = list(engine.get_zones().keys())
        scan_events = engine.start_scan(existing_zones)
        _broadcast_events(scan_events)
        logger.info("Started scanning %d pre-defined zones", len(existing_zones))

    # Healthcheck: Verify Ollama is reachable before starting agent
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    try:
        response = httpx.get(f"{ollama_url.replace('/v1', '')}/api/tags", timeout=2.0)
        if response.status_code != 200:
            raise HTTPException(503, f"Ollama not ready: HTTP {response.status_code}")
        logger.info("Ollama healthcheck passed")
    except httpx.ConnectError:
        raise HTTPException(
            503,
            "Ollama not reachable at %s. Start with: ollama serve" % ollama_url,
        )
    except httpx.ReadTimeout:
        raise HTTPException(
            503, "Ollama timeout at %s. Check if service is running." % ollama_url
        )

    loop = asyncio.get_running_loop()

    tick_task = loop.create_task(_world_tick_loop(engine), name="world_tick")
    agent_task = loop.create_task(
        _agent_loop(engine, req.mission_text, engine.base_col, engine.base_row),
        name="agent_loop",
    )

    # Log unhandled task crashes so they don't vanish silently
    def _on_task_done(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            logger.info("Task %s cancelled.", task.get_name())
        elif exc := task.exception():
            logger.error(
                "Task %s died with unhandled exception:\n%s",
                task.get_name(),
                "".join(traceback.format_exception(exc)),
            )

    tick_task.add_done_callback(_on_task_done)
    agent_task.add_done_callback(_on_task_done)

    _state["tick_task"] = tick_task
    _state["agent_task"] = agent_task
    _state["phase"] = MissionPhase.RUNNING
    _state["mission_text"] = req.mission_text

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

    # Stop agent if running
    agent = _state.get("agent")
    if agent:
        agent.stop()

    return {"ok": True, "phase": "ended"}


# ── Zone endpoints ────────────────────────────────────────────────────────────


@router.post("/zone/add")
async def add_zone(req: ZoneAddRequest) -> dict[str, Any]:
    """
    Register a new search zone on the map.

    Can be called:
    - After /define_map (PENDING phase) - zones added but not scanning
    - During mission (RUNNING phase) - zones added and can be scanned
    - After mission (ENDED phase) - zones added but mission is over

    Note: Use /zone/scan to start scanning a zone (requires RUNNING phase).
    """
    engine: WorldEngine | None = _state.get("engine")
    if engine is None:
        raise HTTPException(400, "No active mission")

    zone_id = f"zone_{uuid.uuid4().hex[:6]}"
    flipped = _flip_polygon(req.geojson_polygon)
    events = engine.add_zone(zone_id, flipped, label=req.label)
    _broadcast_events(events)

    # Auto-start scanning if mission is already running
    if engine.phase == MissionPhase.RUNNING:
        scan_events = engine.start_scan([zone_id])
        _broadcast_events(scan_events)
        logger.info("Auto-started scanning for %s (mission already running)", zone_id)

    # Push to MCP event queue too
    from mcp_server.server import push_events

    push_events(events)

    # Return the zone info
    zone_data = engine.get_zones().get(zone_id, {})
    return {"ok": True, "zone_id": zone_id, "zone": zone_data}


@router.post("/zone/remove")
async def remove_zone(req: ZoneRemoveRequest) -> dict[str, Any]:
    """Remove a zone from the map."""
    engine: WorldEngine | None = _state.get("engine")
    if engine is None:
        raise HTTPException(400, "No active mission")

    events = engine.remove_zone(req.zone_id)
    if not events:
        raise HTTPException(404, f"Zone not found: {req.zone_id}")
    _broadcast_events(events)

    from mcp_server.server import push_events

    push_events(events)

    return {"ok": True, "zone_id": req.zone_id}


@router.post("/zone/scan")
async def scan_zones(req: ZoneScanRequest) -> dict[str, Any]:
    """Start scanning selected zones."""
    engine: WorldEngine | None = _state.get("engine")
    if engine is None:
        raise HTTPException(400, "No active mission")
    if engine.phase != MissionPhase.RUNNING:
        raise HTTPException(400, f"Mission not running, current: {engine.phase.value}")

    events = engine.start_scan(req.zone_ids)
    _broadcast_events(events)

    from mcp_server.server import push_events

    push_events(events)

    return {"ok": True, "scanning": req.zone_ids}


@router.post("/zone/stop")
async def stop_scanning(req: ZoneScanRequest) -> dict[str, Any]:
    """Stop scanning selected zones. Drones keep their last command."""
    engine: WorldEngine | None = _state.get("engine")
    if engine is None:
        raise HTTPException(400, "No active mission")

    events = engine.stop_scan(req.zone_ids)
    _broadcast_events(events)

    from mcp_server.server import push_events

    push_events(events)

    return {"ok": True, "stopped": req.zone_ids}


# ── Agent endpoints ───────────────────────────────────────────────────────────


@router.post("/agent/stop")
async def stop_agent() -> dict[str, Any]:
    """Pause the AI agent loop. Drones keep their last command."""
    agent = _state.get("agent")
    if agent is None:
        raise HTTPException(400, "No active agent")

    agent.pause()
    from world.models import AgentStoppedEvent

    broadcast_event(AgentStoppedEvent())
    return {"ok": True, "agent": "stopped"}


@router.post("/agent/resume")
async def resume_agent() -> dict[str, Any]:
    """Resume the AI agent loop (unpause)."""
    agent = _state.get("agent")
    if agent is None:
        raise HTTPException(400, "No active agent")

    agent.unpause()
    from world.models import AgentResumedEvent

    broadcast_event(AgentResumedEvent())
    return {"ok": True, "agent": "resumed"}


@router.post("/agent/restart")
async def restart_agent() -> dict[str, Any]:
    """Kill the current agent task and start a fresh one with cleared history.
    The world keeps running — drones continue their current paths.
    Use this to recover from a stuck or confused agent.
    """
    engine: WorldEngine | None = _state.get("engine")
    if engine is None:
        raise HTTPException(400, "No active mission")
    if _state.get("phase") != MissionPhase.RUNNING:
        raise HTTPException(400, "Mission is not running")

    # Stop and cancel the current agent task
    old_agent = _state.get("agent")
    if old_agent is not None:
        old_agent.stop()

    old_task = _state.get("agent_task")
    if old_task and not old_task.done():
        old_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(old_task), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    _state["agent"] = None
    _state["agent_task"] = None

    from world.models import AgentResumedEvent

    broadcast_event(AgentResumedEvent())
    logger.info("Agent restarted — launching fresh instance")

    # Retrieve stored mission text (falls back to default)
    mission_text = _state.get("mission_text", "Scan zones for survivors.")

    loop = asyncio.get_running_loop()
    agent_task = loop.create_task(
        _agent_loop(engine, mission_text, engine.base_col, engine.base_row),
        name="agent_loop",
    )

    def _on_task_done(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            logger.info("Task %s cancelled.", task.get_name())
        elif exc := task.exception():
            logger.error(
                "Task %s died:\n%s",
                task.get_name(),
                "".join(traceback.format_exception(exc)),
            )

    agent_task.add_done_callback(_on_task_done)
    _state["agent_task"] = agent_task

    return {"ok": True, "agent": "restarted"}


@router.post("/agent/prompt")
async def prompt_agent(req: AgentPromptRequest) -> dict[str, Any]:
    """Inject a user message into the agent and resume if paused."""
    agent = _state.get("agent")
    if agent is None:
        raise HTTPException(400, "No active agent")

    from world.models import AgentUserMessageEvent

    broadcast_event(AgentUserMessageEvent(content=req.message))
    agent.inject_user_message(req.message)
    return {"ok": True, "message": "queued"}


@router.get("/agent/health")
async def get_agent_health() -> dict[str, Any]:
    """Check if agent is alive and processing."""
    agent = _state.get("agent")
    if agent is None:
        return {"ok": False, "status": "not_started", "message": "No agent exists"}

    is_paused = agent.is_paused
    tick = getattr(agent, "_tick_ref", [0])[0]

    return {
        "ok": True,
        "status": "running" if not is_paused else "paused",
        "tick": tick,
        "message": f"Agent active at tick {tick}",
    }


# ── Query endpoints ───────────────────────────────────────────────────────────


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
      battery_low       — drone battery <= 25%
      survivor_found    — survivor status → found
      zone_added        — new zone registered
      zone_removed      — zone deleted
      scan_started      — zones began scanning
      scan_stopped      — zones stopped scanning
      zone_covered      — all zone cells scanned
      mission_resumed   — mission started
      mission_ended     — mission permanently ended
      out_of_bounds_rejected — move_to target rejected
      agent_thinking    — LLM chain-of-thought
      agent_tool_call   — agent invoked a tool
      agent_tool_result — tool returned result
      agent_stopped     — agent loop paused
      agent_resumed     — agent loop resumed
      agent_user_message — user sent message to agent
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
