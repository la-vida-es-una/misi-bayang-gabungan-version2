"""
Command Agent Orchestrator — Strategic LLM for drone swarm coverage.

Architecture:
  - The LLM makes STRATEGIC decisions: which drone → which zone, when to
    recall for charging, how to react to events.
  - An ALGORITHM (boustrophedon coverage path) handles spatial planning.
  - Tools call WorldEngine DIRECTLY (in-process). The MCP server at /mcp
    exposes the same tools for external access.
  - CoT is captured via middleware and broadcast via SSE.
  - The agent is event-driven: only invoked when something actionable happens
    (drone arrived, battery low, zone covered, new zone added, drone charged).

Token efficiency:
  - System prompt: ~200 tokens (strategic, not spatial).
  - Tool results: concise JSON (~100 tokens each).
  - History: sliding window of last 10 messages.
  - Agent invoked only on events, not every tick.
  - Total per mission: ~15-25 invocations, well within 24k context.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import traceback
from dataclasses import asdict
from typing import Any

from colorama import Fore, Style, init as colorama_init
from dotenv import load_dotenv
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.cot_logger import (
    log_event,
    log_mission,
    log_reasoning,
    log_tool_call,
    log_tool_result,
)
from agent.coverage import generate_coverage_path, truncate_for_battery
from agent.pathfinder import straight_line_path
from world.engine import (
    BATTERY_DRAIN_PER_MOVE,
    SCAN_RADIUS_CELLS,
    WorldEngine,
)
from world.models import (
    AgentErrorEvent,
    AgentThinkingEvent,
    AgentToolCallEvent,
    AgentToolResultEvent,
    WorldEvent,
    ZoneStatus,
)

load_dotenv()
colorama_init(autoreset=True)

logger = logging.getLogger("sar.agent")

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
AGENT_TICK_SEC = float(os.getenv("AGENT_TICK_INTERVAL", "2.0"))
AGENT_CONSUMER = "agent"  # event buffer consumer name

SYSTEM_PROMPT = """\
You are the SAR Swarm Command Agent. Your mission: achieve 100% search \
coverage of all designated zones using autonomous rescue drones.

AVAILABLE TOOLS:
- list_drones(): Discover drones (IDs, battery, status, zone assignment).
- get_zones(): List zones with coverage percentages and status.
- assign_drone_to_zone(drone_id, zone_id): Assign a drone to systematically \
cover a zone. Generates an optimal lawn-mower path automatically.
- recall_drone(drone_id): Send a drone back to base for charging.
- get_mission_status(): Compact mission overview.

RULES:
1. ALWAYS call list_drones() and get_zones() first to understand the situation.
2. If NO zones exist, respond "Waiting for zones" and STOP. Do NOT fly without zones.
3. Assign each idle drone to an uncovered zone using assign_drone_to_zone().
4. When battery_low is reported (<25%), IMMEDIATELY recall that drone.
5. When a drone finishes charging (battery=100%), reassign it to an uncovered zone.
6. When a zone reaches 100% coverage, reassign its drones to remaining zones.
7. Mission is COMPLETE when all zones reach 100%.

THINK STEP BY STEP. Explain your reasoning briefly before each tool call.
Example: "Drone_1 battery is low at 20%, recalling to base for charging."
"""


# ── SSE broadcast helper ─────────────────────────────────────────────────────

_broadcast_error_logged = False


def _broadcast_agent_event(event: Any) -> None:
    """Broadcast agent events via SSE. Import here to avoid circular imports."""
    global _broadcast_error_logged
    try:
        from mission.receiver import broadcast_event

        broadcast_event(event)
        _broadcast_error_logged = False
    except Exception:
        if not _broadcast_error_logged:
            _broadcast_error_logged = True
            logger.error("SSE broadcast failed (suppressing repeats)")


# ── CoT Middleware ────────────────────────────────────────────────────────────


class CoTMiddleware(AgentMiddleware):
    """Captures chain-of-thought and tool calls, broadcasts via SSE."""

    def __init__(self, tick_ref: list[int]) -> None:
        self._tick = tick_ref

    def before_model(self, state: AgentState, runtime: Any) -> None:  # type: ignore[override]
        tick = self._tick[0]
        messages = state.get("messages", [])
        if messages:
            last = messages[-1]
            content = getattr(last, "content", "")
            if content:
                log_reasoning(tick, str(content))
                print(
                    f"{Fore.YELLOW}[tick={tick}] thinking: {content[:200]}{Style.RESET_ALL}"
                )
                _broadcast_agent_event(
                    AgentThinkingEvent(tick=tick, content=str(content))
                )

    def after_model(self, state: AgentState, runtime: Any) -> None:  # type: ignore[override]
        tick = self._tick[0]
        messages = state.get("messages", [])
        if not messages:
            return
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", [])
        for tc in tool_calls:
            name = tc.get("name", "?")
            args = tc.get("args", {})
            log_tool_call(tick, name, args)
            print(f"{Fore.CYAN}[tick={tick}] tool: {name}({args}){Style.RESET_ALL}")
            _broadcast_agent_event(AgentToolCallEvent(tick=tick, tool=name, args=args))


# ── Strategic tool builder ────────────────────────────────────────────────────


def _build_tools(engine: WorldEngine) -> list:
    """Build LangChain @tool functions for strategic drone swarm control.

    These tools operate at the STRATEGIC level — the LLM decides which drone
    goes to which zone, when to recall, etc. Spatial path planning is handled
    algorithmically by the coverage module.
    """

    @tool
    def list_drones() -> str:
        """Discover all active drones. Returns ID, battery %, status, position,
        and current zone assignment for each drone. Always call this first."""
        state = engine.get_world_state()
        assignments = engine.get_drone_assignments()
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
        return json.dumps({"drones": drones, "count": len(drones)})

    @tool
    def get_zones() -> str:
        """Get all search zones with coverage status. Returns zone ID, label,
        status (idle/scanning/completed), and coverage percentage."""
        zones_data = engine.get_zones()
        zones = []
        for zid, z in zones_data.items():
            zones.append(
                {
                    "id": zid,
                    "label": z.get("label", ""),
                    "status": z.get("status", ""),
                    "coverage": f"{z.get('coverage_ratio', 0) * 100:.0f}%",
                    "total_cells": z.get("total_cells", 0),
                }
            )
        return json.dumps({"zones": zones, "count": len(zones)})

    @tool
    def assign_drone_to_zone(drone_id: str, zone_id: str) -> str:
        """Assign a drone to systematically cover a search zone. Automatically
        generates an optimal boustrophedon (lawn-mower) coverage path and
        enables auto-scanning. The drone will cover the zone without further
        commands needed.

        Args:
            drone_id: ID of the drone to assign (e.g. 'drone_1').
            zone_id: ID of the zone to cover.
        """
        # Validate drone
        state = engine.get_world_state()
        drone_state = state["drones"].get(drone_id)
        if drone_state is None:
            return json.dumps({"ok": False, "error": f"Unknown drone: {drone_id}"})

        # Validate zone
        zone = engine.grid.get_zone(zone_id)
        if zone is None:
            return json.dumps({"ok": False, "error": f"Unknown zone: {zone_id}"})

        # Ensure zone is in scanning state
        if zone.status == ZoneStatus.IDLE:
            engine.start_scan([zone_id])
        elif zone.status == ZoneStatus.COMPLETED:
            return json.dumps(
                {"ok": False, "error": f"Zone {zone_id} already 100% covered"}
            )

        # Check if zone has uncovered cells
        if zone.fully_covered:
            return json.dumps(
                {"ok": False, "error": f"Zone {zone_id} already fully covered"}
            )

        # Generate coverage path for remaining uncovered cells
        coverage_path = generate_coverage_path(
            engine.grid, zone_id, scan_radius=SCAN_RADIUS_CELLS
        )
        if not coverage_path:
            return json.dumps({"ok": False, "error": "No uncovered cells in zone"})

        # Generate approach path from drone's current position
        approach = straight_line_path(
            drone_state["col"],
            drone_state["row"],
            coverage_path[0][0],
            coverage_path[0][1],
        )

        # Combine approach + coverage
        full_path = approach + coverage_path

        # Truncate for battery safety
        safe_path = truncate_for_battery(
            full_path,
            drone_battery=drone_state["battery"],
            base_pos=(engine.base_col, engine.base_row),
        )

        if not safe_path:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"Battery too low ({drone_state['battery']:.0f}%). "
                    "Recall for charging first.",
                }
            )

        # Check if we have enough path to actually do coverage (not just approach)
        if len(safe_path) <= len(approach) and len(approach) > 0:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"Battery ({drone_state['battery']:.0f}%) only enough "
                    "for approach, not coverage. Recall for charging first.",
                }
            )

        # Assign to engine
        result = engine.assign_coverage(drone_id, safe_path, zone_id)
        if not result.get("ok"):
            return json.dumps(result)

        battery_cost = len(safe_path) * BATTERY_DRAIN_PER_MOVE
        return json.dumps(
            {
                "ok": True,
                "drone_id": drone_id,
                "zone_id": zone_id,
                "waypoints": result["waypoints"],
                "battery_cost": f"{battery_cost:.0f}%",
                "truncated": len(safe_path) < len(full_path),
            }
        )

    @tool
    def recall_drone(drone_id: str) -> str:
        """Recall a drone to base for charging. Clears its current zone
        assignment and generates a return path.

        Args:
            drone_id: ID of the drone to recall (e.g. 'drone_1').
        """
        result = engine.recall_drone(drone_id)
        return json.dumps(result)

    @tool
    def get_mission_status() -> str:
        """Get a compact mission overview: zone coverages, drone statuses,
        and whether all zones are covered."""
        zones_data = engine.get_zones()
        state = engine.get_world_state()

        zone_summary = {}
        for zid, z in zones_data.items():
            zone_summary[zid] = {
                "coverage": f"{z.get('coverage_ratio', 0) * 100:.0f}%",
                "status": z.get("status", ""),
            }

        all_covered = (
            all(z.get("coverage_ratio", 0) >= 1.0 for z in zones_data.values())
            if zones_data
            else False
        )

        drone_lines = []
        assignments = engine.get_drone_assignments()
        for did, d in state["drones"].items():
            zone = assignments.get(did, "none")
            drone_lines.append(
                f"{did}: bat={d['battery']:.0f}% {d['status']} zone={zone}"
            )

        return json.dumps(
            {
                "tick": state["tick"],
                "zones": zone_summary,
                "all_zones_covered": all_covered,
                "drones": drone_lines,
            }
        )

    return [
        list_drones,
        get_zones,
        assign_drone_to_zone,
        recall_drone,
        get_mission_status,
    ]


# ── Command Agent ─────────────────────────────────────────────────────────────


class CommandAgent:
    def __init__(
        self,
        engine: WorldEngine,
        mission: str,
        base_col: int,
        base_row: int,
    ) -> None:
        self.engine = engine
        self.mission = mission
        self.base_col = base_col
        self.base_row = base_row

        self._tick_ref: list[int] = [0]
        self._history: list[BaseMessage] = []
        self._running = False
        self._paused = False
        self._pause_lock = threading.Lock()

        # Queue for user-injected messages (thread-safe)
        self._user_messages: list[str] = []
        self._user_msg_lock = threading.Lock()

        # Deduplication: don't fire "drone charged" multiple times
        self._charged_notified: set[str] = set()

        # Register as event consumer on the engine
        self.engine.register_event_consumer(AGENT_CONSUMER)

        # Build tools bound to this engine
        tools = _build_tools(engine)

        llm = ChatOpenAI(
            base_url=OLLAMA_BASE_URL,
            api_key=SecretStr("ollama"),
            model=OLLAMA_MODEL,
            temperature=0,
        )

        self._agent = create_agent(
            llm,
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            middleware=[CoTMiddleware(self._tick_ref)],
        )

    # ── Public control ────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        log_mission(f"Mission start: {self.mission}")
        print(f"{Fore.MAGENTA}Mission: {self.mission}{Style.RESET_ALL}")

        # Initial invocation
        try:
            await self._invoke(
                f"Mission: {self.mission}\n"
                f"Base at cell ({self.base_col}, {self.base_row}).\n"
                "Discover the fleet and zones, then assign drones to coverage."
            )
        except Exception as exc:
            self._running = False
            logger.error("Initial agent invoke failed: %s", exc)
            raise

        while self._running:
            await asyncio.sleep(AGENT_TICK_SEC)

            if self._paused:
                user_msgs = self._drain_user_messages()
                if user_msgs:
                    self._paused = False
                    for msg in user_msgs:
                        await self._invoke(f"[User message] {msg}")
                continue

            try:
                await self._agent_tick()
            except Exception as exc:
                tb = traceback.format_exc()
                tick = self._tick_ref[0]
                logger.error("Agent tick %d failed:\n%s", tick, tb)
                print(f"{Fore.RED}[tick={tick}] agent error:\n{tb}{Style.RESET_ALL}")
                log_mission(f"Agent tick error: {exc}")
                _broadcast_agent_event(
                    AgentErrorEvent(tick=tick, error=str(exc), detail=tb)
                )

    def stop(self) -> None:
        self._running = False

    def pause(self) -> None:
        with self._pause_lock:
            self._paused = True

    def unpause(self) -> None:
        with self._pause_lock:
            self._paused = False

    def inject_user_message(self, message: str) -> None:
        with self._user_msg_lock:
            self._user_messages.append(message)

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ── Event-driven agent tick ───────────────────────────────────────────────

    async def _agent_tick(self) -> None:
        """Process world events and invoke LLM only when action is needed."""
        self._tick_ref[0] += 1
        tick = self._tick_ref[0]

        # Drain events from engine
        raw_events: list[WorldEvent] = self.engine.drain_events(AGENT_CONSUMER)
        events: list[dict[str, Any]] = [asdict(e) for e in raw_events]  # type: ignore[arg-type]

        # Log all events
        for ev in events:
            log_event(tick, ev)

        # Build actionable triggers from events
        triggers: list[str] = []

        for ev in events:
            etype = ev.get("type")

            if etype == "drone_arrived":
                did = ev.get("drone_id", "?")
                triggers.append(
                    f"Drone {did} finished its path at ({ev.get('col')},{ev.get('row')}) "
                    "and is now idle. Check zone coverage and reassign if needed."
                )
                self._charged_notified.discard(did)

            elif etype == "battery_low":
                did = ev.get("drone_id", "?")
                bat = ev.get("battery", 0)
                triggers.append(
                    f"URGENT: Drone {did} battery LOW at {bat:.0f}%. "
                    "Recall to base IMMEDIATELY with recall_drone()."
                )

            elif etype == "zone_covered":
                zid = ev.get("zone_id", "?")
                triggers.append(
                    f"Zone {zid} reached 100% coverage! "
                    "Check if other zones still need coverage."
                )

            elif etype == "zone_added":
                zid = ev.get("zone_id", "?")
                label = ev.get("label", "")
                triggers.append(
                    f"New zone added: {zid} ({label}). Assign idle drones to cover it."
                )

            elif etype == "survivor_found":
                sid = ev.get("survivor_id", "?")
                did = ev.get("drone_id", "?")
                triggers.append(f"Survivor {sid} found by {did}!")

            elif etype == "drone_charging":
                did = ev.get("drone_id", "?")
                bat = ev.get("battery", 0)
                if bat >= 100.0 and did not in self._charged_notified:
                    self._charged_notified.add(did)
                    triggers.append(
                        f"Drone {did} fully charged (100%). Ready for assignment."
                    )

        # Check for user-injected messages
        user_msgs = self._drain_user_messages()
        for msg in user_msgs:
            triggers.append(f"[User message] {msg}")

        # Only invoke LLM when there are actionable triggers
        if not triggers:
            return

        prompt = "\n".join(triggers)
        await self._invoke(prompt)

    def _drain_user_messages(self) -> list[str]:
        with self._user_msg_lock:
            msgs = list(self._user_messages)
            self._user_messages.clear()
            return msgs

    # ── Agent invocation ──────────────────────────────────────────────────────

    async def _invoke(self, user_message: str) -> None:
        loop = asyncio.get_running_loop()

        input_messages: list[BaseMessage] = [
            *self._history,
            HumanMessage(content=user_message),
        ]
        agent_input: dict[str, list[BaseMessage]] = {"messages": input_messages}

        try:
            result: dict[str, Any] = await loop.run_in_executor(
                None,
                lambda: self._agent.invoke(agent_input),  # pyright: ignore[reportArgumentType]
            )
        except Exception as exc:
            tb = traceback.format_exc()
            tick = self._tick_ref[0]
            logger.error("Agent invoke failed at tick %d:\n%s", tick, tb)
            print(f"{Fore.RED}[tick={tick}] invoke error:\n{tb}{Style.RESET_ALL}")
            log_mission(f"Invoke error: {exc}")
            _broadcast_agent_event(
                AgentErrorEvent(tick=tick, error=str(exc), detail=tb)
            )
            return

        # Process result messages
        out_messages: list[Any] = result.get("messages", [])
        tick = self._tick_ref[0]

        for msg in out_messages:
            tool_calls = getattr(msg, "tool_calls", [])
            for tc in tool_calls:
                name: str = tc.get("name", "?")
                args: dict[str, Any] = tc.get("args", {})
                log_tool_result(tick, name, args)
                _broadcast_agent_event(
                    AgentToolResultEvent(tick=tick, tool=name, result=args)
                )
                print(f"{Fore.GREEN}[tick={tick}] {name} -> {args}{Style.RESET_ALL}")

            content = getattr(msg, "content", "")
            if content and not tool_calls and isinstance(msg, AIMessage):
                logger.debug("[tick=%d] AI: %s", tick, content[:200])

        # Update history — sliding window for context management
        self._history.append(HumanMessage(content=user_message))
        if out_messages:
            last = out_messages[-1]
            self._history.append(AIMessage(content=getattr(last, "content", "")))
        self._history = self._history[-10:]
