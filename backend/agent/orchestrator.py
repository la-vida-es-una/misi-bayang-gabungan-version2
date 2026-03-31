"""
Command Agent Orchestrator — strategic drone swarm coordination.

Architecture (single-tier, strategic only):

  The LLM makes strategic decisions: which drone → which zone, when to
  recall for charging, how to react to zone completion / new zones.
  Invoked only on high-level events (~15-25 calls per mission).

  Drones are autonomous: once assigned to a zone, the WorldEngine
  auto-scans at each waypoint and advances to the next waypoint
  inline within _tick_drone().  No MCP round-trips needed on the
  hot path.

MCP compliance:
  MCP tools (thermal_scan, move_to, etc.) remain exposed for
  study-case compliance but the hot path no longer round-trips
  through the agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import traceback
from dataclasses import asdict
from typing import Any, final

from colorama import Fore, Style
from colorama import init as colorama_init
from dotenv import load_dotenv
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.cot_logger import (
    log_event,
    log_mission,
    log_reasoning,
    log_tool_call,
    log_tool_result,
)
from agent.state_builder import build_mission_state_summary
from world.engine import WorldEngine
from world.models import (
    AgentErrorEvent,
    AgentResumedEvent,
    AgentStoppedEvent,
    AgentThinkingEvent,
    AgentToolCallEvent,
    AgentToolResultEvent,
    WorldEvent,
)

_ = load_dotenv()
colorama_init(autoreset=True)

logger = logging.getLogger("sar.agent")

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
AGENT_TICK_SEC = float(os.getenv("AGENT_TICK_INTERVAL", "2.0"))
AGENT_MAX_ITER = int(os.getenv("AGENT_MAX_ITERATIONS", "16"))
AGENT_INVOKE_TIMEOUT = float(os.getenv("AGENT_INVOKE_TIMEOUT", "120.0"))
MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://localhost:8000/mcp/mcp")
AGENT_CONSUMER = "agent"

SYSTEM_PROMPT = """\
You are a strategic SAR Swarm Coordinator. Drones autonomously scan once assigned.

MISSION STATE: Each turn starts with a [MISSION STATE] block — trust it.

TOOLS:
- auto_assign_fleet(): Deploy ALL idle drones to zones (preferred).
- assign_drone_to_zone(drone_id, zone_id): Assign one drone precisely.
- recall_drone(drone_id): Send drone to base for charging.
- list_drones() / get_zones() / get_mission_status(): Query state if needed.

Drones auto-scan waypoints — do NOT call thermal_scan or move_to directly.

RULES:
1. Read the mission state first — it shows assignments and coverage.
2. Do NOT reassign busy drones (moving/scanning).
3. Use auto_assign_fleet() to deploy idle drones.
4. On battery_low (<25%), IMMEDIATELY recall that drone.
5. On drone charged (100%), reassign with auto_assign_fleet().
6. On zone 100%, redistribute idle drones.
7. Maximum 3 tool calls per turn. One tool at a time.

STOP after any successful assignment/recall or if all drones are busy.
"""

# Strategic tools the LLM may call.  Other MCP tools (thermal_scan, move_to)
# remain exposed for study-case compliance but are not on the hot path.
STRATEGIC_TOOL_NAMES = {
    "list_drones",
    "get_zones",
    "auto_assign_fleet",
    "assign_drone_to_zone",
    "recall_drone",
    "get_mission_status",
}


# ── SSE broadcast helper ─────────────────────────────────────────────────────

_broadcast_error_logged = False


def _broadcast_agent_event(event: Any) -> None:
    global _broadcast_error_logged
    try:
        from mission.receiver import broadcast_event

        broadcast_event(event)
        _broadcast_error_logged = False
    except Exception:
        if not _broadcast_error_logged:
            _broadcast_error_logged = True
            logger.error("SSE broadcast failed (suppressing repeats)")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_tool_result(raw: Any) -> dict[str, Any]:
    """Parse a tool result into a dict suitable for SSE broadcast."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"output": raw}
    elif isinstance(raw, dict):
        return raw
    else:
        return {"output": str(raw)}


# ── CoT Middleware ────────────────────────────────────────────────────────────


@final
class CoTMiddleware(AgentMiddleware):
    """Captures chain-of-thought, tool calls, and tool results — broadcasts via SSE.

    Tool calls are broadcast in after_model (when the LLM generates them).
    Tool results are broadcast in before_model (when tools have executed and
    the agent is about to call the LLM again).  This ensures tool_call → tool_result
    ordering in the SSE stream, even within a multi-turn ainvoke().
    """

    def __init__(self, tick_ref: list[int]) -> None:
        self._tick = tick_ref
        self._broadcasted_results: set[str] = set()

    def reset(self) -> None:
        """Clear state between invocations."""
        self._broadcasted_results.clear()

    def before_model(self, state: AgentState, runtime: Any) -> None:  # type: ignore[override]
        """Broadcast tool results that appeared since the last LLM call."""
        tick = self._tick[0]
        messages = state.get("messages", [])
        for msg in messages:
            if not isinstance(msg, ToolMessage):
                continue
            tool_call_id: str = getattr(msg, "tool_call_id", "") or ""
            if tool_call_id and tool_call_id in self._broadcasted_results:
                continue
            if tool_call_id:
                self._broadcasted_results.add(tool_call_id)
            tool_name: str = getattr(msg, "name", "?")
            result_data = _parse_tool_result(msg.content)
            log_tool_result(tick, tool_name, result_data, call_id=tool_call_id)
            print(
                f"{Fore.GREEN}[tick={tick}] {tool_name} -> {str(result_data)[:120]}{Style.RESET_ALL}"
            )
            _broadcast_agent_event(
                AgentToolResultEvent(
                    tick=tick, tool=tool_name, result=result_data, call_id=tool_call_id
                )
            )

    def after_model(self, state: AgentState, runtime: Any) -> None:  # type: ignore[override]
        tick = self._tick[0]
        messages = state.get("messages", [])
        if not messages:
            return
        last = messages[-1]
        # Broadcast AI reasoning text (always, even if tool_calls follow — this is CoT)
        content = getattr(last, "content", "")
        if content and isinstance(last, AIMessage):
            log_reasoning(tick, str(content))
            print(
                f"{Fore.YELLOW}[tick={tick}] thinking: {str(content)[:200]}{Style.RESET_ALL}"
            )
            _broadcast_agent_event(AgentThinkingEvent(tick=tick, content=str(content)))
        # Broadcast tool calls with call_id
        tool_calls = getattr(last, "tool_calls", [])
        for tc in tool_calls:
            name = tc.get("name", "?")
            args = tc.get("args", {})
            call_id = tc.get("id", "")
            log_tool_call(tick, name, args, call_id=call_id)
            print(f"{Fore.CYAN}[tick={tick}] tool: {name}({args}){Style.RESET_ALL}")
            _broadcast_agent_event(
                AgentToolCallEvent(tick=tick, tool=name, args=args, call_id=call_id)
            )


# ── Command Agent ─────────────────────────────────────────────────────────────


@final
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

        self._user_messages: list[str] = []
        self._user_msg_lock = threading.Lock()
        self._charged_notified: set[str] = set()

        # MCP client + tools loaded during run() (async context needed)
        self._mcp_client: MultiServerMCPClient | None = None
        self._all_tools: list = []  # pyright: ignore[reportMissingTypeArgument]
        self._strategic_tools: list = []  # pyright: ignore[reportMissingTypeArgument]
        self._tool_map: dict[str, Any] = {}

        # Track key events for state summary injection (memory-proof)
        self._recent_key_events: list[dict[str, Any]] = []

        self.engine.register_event_consumer(AGENT_CONSUMER)

    # ── Public control ────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        log_mission(f"Mission start: {self.mission}")
        print(f"{Fore.MAGENTA}Mission: {self.mission}{Style.RESET_ALL}")

        # Connect to MCP server and load tools (v0.1.0+ API — no context manager)
        self._mcp_client = MultiServerMCPClient(
            {
                "sar-swarm": {
                    "transport": "streamable_http",
                    "url": MCP_BASE_URL,
                },
            }
        )

        self._all_tools = await self._mcp_client.get_tools()
        self._tool_map = {t.name: t for t in self._all_tools}
        self._strategic_tools = [
            t for t in self._all_tools if t.name in STRATEGIC_TOOL_NAMES
        ]
        logger.info(
            "MCP tools loaded: %s",
            [t.name for t in self._all_tools],
        )

        # Build the LLM agent with ONLY strategic tools
        llm = ChatOpenAI(
            base_url=OLLAMA_BASE_URL,
            api_key=SecretStr("ollama"),
            model=OLLAMA_MODEL,
            temperature=0,
        )
        self._cot_middleware = CoTMiddleware(self._tick_ref)
        self._agent = create_agent(
            llm,
            tools=self._strategic_tools,
            system_prompt=SYSTEM_PROMPT,
            middleware=[self._cot_middleware],
        )

        # Initial invocation — start tick at 1 so initial tool calls don't log [tick 0]
        self._tick_ref[0] = 1
        await self._invoke(
            f"Mission: {self.mission}\n"
            + f"Base at cell ({self.base_col}, {self.base_row}).\n"
            + "Discover the fleet and zones, then assign drones to coverage."
        )

        while self._running:
            await asyncio.sleep(AGENT_TICK_SEC)
            if self._paused:
                # User messages always wake the agent
                user_msgs = self._drain_user_messages()
                if user_msgs:
                    self._paused = False
                    _broadcast_agent_event(AgentResumedEvent())
                    for msg in user_msgs:
                        await self._invoke(f"[User message] {msg}")
                    continue
                # Engine events also wake the agent, but only if actionable
                pending = self.engine.drain_events(AGENT_CONSUMER)
                # Filter to only events that need LLM attention when paused
                RESUME_EVENT_TYPES = {"zone_added", "battery_low"}
                actionable = [e for e in pending if getattr(e, "type", None) in RESUME_EVENT_TYPES]
                if actionable:
                    self._paused = False
                    _broadcast_agent_event(AgentResumedEvent())
                    # Pass all pre-drained events (including non-actionable) into _agent_tick
                    try:
                        await self._agent_tick(pre_drained=pending)
                    except Exception as exc:
                        tb = traceback.format_exc()
                        tick = self._tick_ref[0]
                        logger.error("Agent tick %d failed:\n%s", tick, tb)
                        print(f"{Fore.RED}[tick={tick}] agent error:\n{tb}{Style.RESET_ALL}")
                        log_mission(f"Agent tick error: {exc}")
                        _broadcast_agent_event(
                            AgentErrorEvent(tick=tick, error=str(exc), detail=tb)
                        )
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

    def _check_auto_pause(self, tick: int) -> None:
        """Auto-pause when all zones are completed and no drones are active."""
        zones_data = self.engine.get_zones()
        if not zones_data:
            return
        all_done = all(
            z.get("status") == "completed" for z in zones_data.values()
        )
        if not all_done:
            return
        # Verify no drones are still working
        assignments = self.engine.get_drone_assignments()
        any_assigned = any(z is not None for z in assignments.values())
        if any_assigned:
            return
        # All zones done, no drones assigned — auto-pause
        self._paused = True
        log_mission("All zones completed — agent auto-paused, waiting for new zones")
        print(
            f"{Fore.MAGENTA}[tick={tick}] All zones 100% — agent paused, waiting for new zones{Style.RESET_ALL}"
        )
        _broadcast_agent_event(AgentStoppedEvent())

    # ── Event-driven agent tick ───────────────────────────────────────────────

    async def _agent_tick(
        self, pre_drained: list[WorldEvent] | None = None
    ) -> None:
        raw_events: list[WorldEvent] = (
            pre_drained
            if pre_drained is not None
            else self.engine.drain_events(AGENT_CONSUMER)
        )
        user_msgs = self._drain_user_messages()

        # Nothing to do — don't increment tick
        if not raw_events and not user_msgs:
            return

        self._tick_ref[0] += 1
        tick = self._tick_ref[0]

        events: list[dict[str, Any]] = [asdict(e) for e in raw_events]  # type: ignore[arg-type]

        for ev in events:
            log_event(tick, ev)

        # Build LLM triggers from events (strategic decisions only)
        triggers: list[str] = []

        for ev in events:
            etype = ev.get("type")

            # Track key events for memory-proof state injection
            self._track_key_event(tick, ev)

            if etype == "drone_arrived":
                # drone_arrived only fires when scan queue is empty (drone truly idle)
                did = ev.get("drone_id", "?")
                triggers.append(
                    f"Drone {did} finished coverage at ({ev.get('col')},{ev.get('row')}) "
                    + "and is now idle. Check zone coverage and reassign if needed."
                )
                self._charged_notified.discard(did)

            elif etype == "battery_low":
                did = ev.get("drone_id", "?")
                bat = ev.get("battery", 0)
                triggers.append(
                    f"URGENT: Drone {did} battery LOW at {bat:.0f}%. "
                    + "Recall to base IMMEDIATELY with recall_drone()."
                )

            elif etype == "zone_covered":
                zid = ev.get("zone_id", "?")
                triggers.append(
                    f"Zone {zid} reached 100% coverage! "
                    + "Check if other zones still need coverage."
                )

            elif etype == "zone_added":
                zid = ev.get("zone_id", "?")
                triggers.append(
                    f"New zone {zid} added. Assign idle drones with auto_assign_fleet()."
                )

            elif etype == "survivor_found":
                sid = ev.get("survivor_id", "?")
                did = ev.get("drone_id", "?")
                triggers.append(f"SURVIVOR {sid} found by {did}!")

            elif etype == "drone_charging":
                did = ev.get("drone_id", "?")
                bat = ev.get("battery", 0)
                if bat >= 100.0 and did not in self._charged_notified:
                    self._charged_notified.add(did)
                    triggers.append(
                        f"Drone {did} fully charged (100%). Ready for assignment."
                    )

            elif etype == "drone_scanned":
                # Too frequent — just log, don't wake the agent
                pass

        for msg in user_msgs:
            triggers.append(f"[User message] {msg}")

        # Deduplicate strategic triggers — collapse repeated identical triggers
        if triggers:
            seen: set[str] = set()
            deduped: list[str] = []
            for t in triggers:
                if t not in seen:
                    seen.add(t)
                    deduped.append(t)
            prompt = "\n".join(deduped)
            await self._invoke(prompt)

        # AUTO-PAUSE: all zones completed and no drones actively working
        self._check_auto_pause(tick)

    def _drain_user_messages(self) -> list[str]:
        with self._user_msg_lock:
            msgs = list(self._user_messages)
            self._user_messages.clear()
            return msgs

    def _format_event_summary(self, ev: dict[str, Any]) -> str:
        """Format a world event as a concise summary string for memory tracking."""
        ev_type = ev.get("type", "")
        if ev_type == "survivor_found":
            return f"survivor {ev.get('survivor_id', '?')} found by {ev.get('drone_id', '?')}"
        elif ev_type == "zone_covered":
            return f"zone {ev.get('zone_id', '?')} completed 100%"
        elif ev_type == "battery_low":
            return f"{ev.get('drone_id', '?')} battery low ({ev.get('battery', '?'):.0f}%)"
        elif ev_type == "drone_arrived":
            return f"{ev.get('drone_id', '?')} arrived at ({ev.get('col')}, {ev.get('row')})"
        return f"{ev_type}: {ev.get('drone_id', '?')}"

    def _track_key_event(self, tick: int, ev: dict[str, Any]) -> None:
        """Track a key event for state summary injection."""
        KEY_EVENT_TYPES = {"survivor_found", "zone_covered", "battery_low"}
        ev_type = ev.get("type", "")
        if ev_type in KEY_EVENT_TYPES:
            summary = self._format_event_summary(ev)
            self._recent_key_events.append({"tick": tick, "type": ev_type, "summary": summary})
            # Keep only last 10 key events
            self._recent_key_events = self._recent_key_events[-10:]

    # ── Agent invocation (LLM via MCP tools) ──────────────────────────────────

    async def _invoke(self, user_message: str) -> None:
        tick = self._tick_ref[0]

        # Reset middleware state for new invocation
        self._cot_middleware.reset()

        # Build state summary from WorldEngine (memory-proof context injection)
        state_summary = build_mission_state_summary(
            engine=self.engine,
            tick=tick,
            recent_events=self._recent_key_events,
        )

        # Inject state summary as first message, then recent history, then trigger
        input_messages: list[BaseMessage] = [
            HumanMessage(content=state_summary.to_prompt_block()),  # Always-fresh state
            *self._history[-6:],  # Reduced from 10 to 6 for token efficiency
            HumanMessage(content=user_message),
        ]
        n_input = len(input_messages)
        agent_input: dict[str, list[BaseMessage]] = {"messages": input_messages}

        try:
            result: dict[str, Any] = await asyncio.wait_for(
                self._agent.ainvoke(  # pyright: ignore[reportArgumentType]
                    agent_input,
                    config={"recursion_limit": AGENT_MAX_ITER},
                ),
                timeout=AGENT_INVOKE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            tick = self._tick_ref[0]
            logger.warning("Agent invoke timed out at tick %d", tick)
            log_mission(f"Agent invoke timed out at tick {tick}")
            _broadcast_agent_event(
                AgentErrorEvent(
                    tick=tick,
                    error="Agent invocation timed out",
                    detail=f"Timeout after {AGENT_INVOKE_TIMEOUT}s",
                )
            )
            return
        except Exception as exc:
            tb = traceback.format_exc()
            tick = self._tick_ref[0]
            is_recursion = "recursion" in str(exc).lower()
            error_msg = "Agent hit tool-call loop limit" if is_recursion else str(exc)
            logger.error("Agent invoke failed at tick %d:\n%s", tick, tb)
            print(f"{Fore.RED}[tick={tick}] invoke error:\n{tb}{Style.RESET_ALL}")
            log_mission(f"Invoke error: {error_msg}")
            _broadcast_agent_event(
                AgentErrorEvent(tick=tick, error=error_msg, detail=tb)
            )
            return

        # Only process messages generated during this invocation (not input history)
        all_messages: list[Any] = result.get("messages", [])
        new_messages = all_messages[n_input:]
        tick = self._tick_ref[0]

        # Broadcast any tool results NOT already broadcast by CoTMiddleware.
        # This catches edge cases like the last tool round before ainvoke() returns.
        for msg in new_messages:
            if isinstance(msg, ToolMessage):
                tool_call_id: str = getattr(msg, "tool_call_id", "") or ""
                if tool_call_id and tool_call_id in self._cot_middleware._broadcasted_results:
                    continue  # Already broadcast by middleware
                tool_name: str = getattr(msg, "name", "?")
                result_data = _parse_tool_result(msg.content)
                log_tool_result(tick, tool_name, result_data, call_id=tool_call_id)
                _broadcast_agent_event(
                    AgentToolResultEvent(
                        tick=tick, tool=tool_name, result=result_data, call_id=tool_call_id
                    )
                )
                print(
                    f"{Fore.GREEN}[tick={tick}] {tool_name} -> {str(result_data)[:120]}{Style.RESET_ALL}"
                )

        self._history.append(HumanMessage(content=user_message))
        if new_messages:
            last = new_messages[-1]
            self._history.append(AIMessage(content=getattr(last, "content", "")))
        self._history = self._history[-6:]  # Reduced from 10 (state injection handles context)
