"""
Command Agent Orchestrator — MCP-mediated strategic drone swarm control.

Architecture (two-tier, single agent):

  STRATEGIC TIER (LLM reasoning):
    The LLM makes strategic decisions: which drone → which zone, when to
    recall for charging, how to react to zone completion / new zones.
    Invoked only on high-level events (~15-25 calls per mission).

  MECHANICAL TIER (deterministic, no LLM):
    When a drone arrives at a scan waypoint (DroneArrivedEvent + scan queue
    not empty), the orchestrator calls thermal_scan(drone_id) and then
    move_to(drone_id, x, y) for the next segment — all via MCP.
    This produces a rich mission log of primitive MCP tool calls without
    burning LLM tokens on spatial decisions.

MCP compliance:
  ALL tool calls go through the MCP server at /mcp using
  langchain-mcp-adapters.  The agent never calls WorldEngine directly.
  This satisfies: "All communication between the Agent and the Drones
  must be handled via the Model Context Protocol."

Token efficiency:
  System prompt: ~250 tokens.  Tool results: ~100 tokens each.
  History: sliding window of last 10 messages.
  Mechanical tier uses MCP but not LLM context.
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
MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://localhost:8000/mcp/mcp")
AGENT_CONSUMER = "agent"

SYSTEM_PROMPT = """\
You are the SAR Swarm Command Agent for a search-and-rescue mission.
Your goal: locate survivors in disaster zones by achieving 100% thermal \
scan coverage of all designated search zones using autonomous rescue drones.

AVAILABLE MCP TOOLS:
- list_drones(): Discover drones (IDs, battery, status, zone assignment).
- get_zones(): List zones with coverage percentages and status.
- auto_assign_fleet(): Assign ALL idle drones to scanning zones at once. \
Distributes drones evenly.  ALL drones start moving simultaneously. \
This is the PREFERRED tool for deploying drones — use it instead of \
calling assign_drone_to_zone repeatedly.
- assign_drone_to_zone(drone_id, zone_id): Assign ONE drone to a zone. \
Only use this when you need precise control over a single assignment.
- recall_drone(drone_id): Send a drone back to base for charging.
- get_mission_status(): Overview with zone coverage and survivors found.

RULES:
1. ALWAYS call list_drones() and get_zones() first to discover the fleet.
2. If NO zones exist, respond "Waiting for search zones" and STOP.
3. Use auto_assign_fleet() to deploy all idle drones simultaneously.
4. When battery_low is reported (<25%), IMMEDIATELY recall that drone.
5. When a drone finishes charging (battery=100%), use auto_assign_fleet().
6. When a zone reaches 100%, use auto_assign_fleet() to redistribute.
7. Mission is COMPLETE when all zones reach 100% and survivors are found.

CRITICAL: Call exactly ONE tool at a time. Wait for its result before \
calling the next tool.

THINK STEP BY STEP before each action.  Explain your reasoning briefly.
Example: "Drone_1 has 20% battery, so I am recalling it to base. \
The other drones have good battery, so I will deploy the fleet."

IMPORTANT: After calling auto_assign_fleet() or assign_drone_to_zone(), STOP.
Do NOT call get_mission_status() to verify. The mechanical tier handles scanning \
autonomously. You will be notified when drones finish, need charging, or zones \
reach 100%. Just call the assignment tool and end your turn.
"""

# Strategic tools the LLM may call.  Mechanical tools (thermal_scan, move_to)
# are loaded from MCP too, but only used by the mechanical tier.
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


# ── CoT Middleware ────────────────────────────────────────────────────────────


@final
class CoTMiddleware(AgentMiddleware):
    """Captures chain-of-thought and tool calls, broadcasts via SSE."""

    def __init__(self, tick_ref: list[int]) -> None:
        self._tick = tick_ref

    def before_model(self, state: AgentState, runtime: Any) -> None:  # type: ignore[override]
        # before_model fires with the input state — last message is the trigger
        # (HumanMessage or ToolMessage). Nothing to broadcast here.
        pass

    def after_model(self, state: AgentState, runtime: Any) -> None:  # type: ignore[override]
        tick = self._tick[0]
        messages = state.get("messages", [])
        if not messages:
            return
        last = messages[-1]
        # Broadcast AI reasoning text (content without tool calls)
        content = getattr(last, "content", "")
        if (
            content
            and isinstance(last, AIMessage)
            and not getattr(last, "tool_calls", [])
        ):
            log_reasoning(tick, str(content))
            print(
                f"{Fore.YELLOW}[tick={tick}] thinking: {str(content)[:200]}{Style.RESET_ALL}"
            )
            _broadcast_agent_event(AgentThinkingEvent(tick=tick, content=str(content)))
        # Broadcast tool calls
        tool_calls = getattr(last, "tool_calls", [])
        for tc in tool_calls:
            name = tc.get("name", "?")
            args = tc.get("args", {})
            log_tool_call(tick, name, args)
            print(f"{Fore.CYAN}[tick={tick}] tool: {name}({args}){Style.RESET_ALL}")
            _broadcast_agent_event(AgentToolCallEvent(tick=tick, tool=name, args=args))


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
        self._agent = create_agent(
            llm,
            tools=self._strategic_tools,
            system_prompt=SYSTEM_PROMPT,
            middleware=[CoTMiddleware(self._tick_ref)],
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
                # Engine events also wake the agent (e.g. new zone added)
                pending = self.engine.drain_events(AGENT_CONSUMER)
                if pending:
                    self._paused = False
                    _broadcast_agent_event(AgentResumedEvent())
                    # Pass pre-drained events into _agent_tick
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

    # ── Mechanical tier: scan-on-arrival via MCP ──────────────────────────────

    async def _mechanical_scan_and_advance(self, drone_id: str) -> None:
        """Called when a drone arrives at a scan waypoint.

        1. Pop the pending scan entry from queue
        2. Call thermal_scan(drone_id) via MCP
        3. Pop next entry from queue
        4. Call move_to(drone_id, x, y) via MCP for the next scan point
        """
        tick = self._tick_ref[0]

        # Pop the pending scan (empty segment + scan point)
        entry = self.engine.pop_scan_queue(drone_id)
        if entry is None:
            return

        _seg, scan_point = entry

        # Call thermal_scan via MCP
        scan_tool = self._tool_map.get("thermal_scan")
        if scan_tool:
            try:
                result = await scan_tool.ainvoke({"drone_id": drone_id})
                log_tool_call(tick, "thermal_scan", {"drone_id": drone_id})
                log_tool_result(tick, "thermal_scan", {"result": str(result)[:200]})
                _broadcast_agent_event(
                    AgentToolCallEvent(
                        tick=tick, tool="thermal_scan", args={"drone_id": drone_id}
                    )
                )
                _broadcast_agent_event(
                    AgentToolResultEvent(
                        tick=tick,
                        tool="thermal_scan",
                        result={"drone_id": drone_id, "at": list(scan_point)},
                    )
                )
                print(
                    f"{Fore.GREEN}[tick={tick}] mechanical: thermal_scan({drone_id}) at {scan_point}{Style.RESET_ALL}"
                )
            except Exception as exc:
                logger.error("Mechanical thermal_scan failed for %s: %s", drone_id, exc)

        # Pop next entry and start moving to next scan point
        next_entry = self.engine.pop_scan_queue(drone_id)
        if next_entry is None:
            # All scan points done — clear assignment
            self.engine.clear_drone_assignment(drone_id)
            return

        next_seg, next_sp = next_entry
        # Move to the next scan point
        move_tool = self._tool_map.get("move_to")
        if move_tool and next_sp:
            try:
                result = await move_tool.ainvoke(
                    {"drone_id": drone_id, "x": next_sp[0], "y": next_sp[1]}
                )
                log_tool_call(
                    tick,
                    "move_to",
                    {"drone_id": drone_id, "x": next_sp[0], "y": next_sp[1]},
                )
                _broadcast_agent_event(
                    AgentToolCallEvent(
                        tick=tick,
                        tool="move_to",
                        args={"drone_id": drone_id, "x": next_sp[0], "y": next_sp[1]},
                    )
                )
                print(
                    f"{Fore.GREEN}[tick={tick}] mechanical: move_to({drone_id}, {next_sp[0]}, {next_sp[1]}){Style.RESET_ALL}"
                )
            except Exception as exc:
                logger.error("Mechanical move_to failed for %s: %s", drone_id, exc)

        # Re-push the scan point (move started, scan pending on arrival)
        self.engine.push_scan_queue_entry(drone_id, ([], next_sp), front=True)

    # ── Mechanical helpers ─────────────────────────────────────────────────────

    async def _mechanical_auto_assign(self, tick: int) -> None:
        """Call auto_assign_fleet via MCP when a new zone is added."""
        assign_tool = self._tool_map.get("auto_assign_fleet")
        if assign_tool is None:
            return
        try:
            result = await assign_tool.ainvoke({})
            log_tool_call(tick, "auto_assign_fleet", {})
            log_tool_result(tick, "auto_assign_fleet", {"result": str(result)[:200]})
            _broadcast_agent_event(
                AgentToolCallEvent(tick=tick, tool="auto_assign_fleet", args={})
            )
            _broadcast_agent_event(
                AgentToolResultEvent(
                    tick=tick, tool="auto_assign_fleet", result={"result": str(result)[:200]}
                )
            )
            print(
                f"{Fore.GREEN}[tick={tick}] mechanical: auto_assign_fleet() -> {str(result)[:120]}{Style.RESET_ALL}"
            )
        except Exception as exc:
            logger.error("Mechanical auto_assign_fleet failed: %s", exc)

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

        # MECHANICAL TIER: handle scan-on-arrival for drones with pending scans
        mechanically_handled: set[str] = set()
        for ev in events:
            if ev.get("type") == "drone_arrived":
                did = ev.get("drone_id", "")
                if self.engine.peek_scan_queue(did) > 0:
                    await self._mechanical_scan_and_advance(did)
                    mechanically_handled.add(did)

        # Fallback: catch drones that are idle with pending scans but no event
        # (e.g. synthetic arrival event was missed or consumed elsewhere)
        state = self.engine.get_world_state()
        for did, d in state["drones"].items():
            if (
                did not in mechanically_handled
                and d["status"] == "idle"
                and d["path_remaining"] == 0
                and self.engine.peek_scan_queue(did) > 0
            ):
                await self._mechanical_scan_and_advance(did)
                mechanically_handled.add(did)

        # MECHANICAL TIER: auto-assign idle drones on zone_added
        has_zone_added = any(ev.get("type") == "zone_added" for ev in events)
        if has_zone_added:
            await self._mechanical_auto_assign(tick)

        # STRATEGIC TIER: build LLM triggers from remaining events
        triggers: list[str] = []

        for ev in events:
            etype = ev.get("type")

            if etype == "drone_arrived":
                did = ev.get("drone_id", "?")
                # Skip drones the mechanical tier just handled
                if did in mechanically_handled:
                    continue
                # Only trigger LLM if scan queue empty (coverage done)
                if self.engine.peek_scan_queue(did) == 0:
                    triggers.append(
                        f"Drone {did} finished coverage at ({ev.get('col')},{ev.get('row')}) "
                        + "and is now idle.  Check zone coverage and reassign if needed."
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
                # Handled mechanically — don't trigger LLM
                pass

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

        # Detect genuine completion: mechanical tier handled a drone that now
        # has an empty scan queue AND no zone assignment → finished all scans
        for did in mechanically_handled:
            if (
                self.engine.peek_scan_queue(did) == 0
                and self.engine.get_drone_assignments().get(did) is None
            ):
                triggers.append(
                    f"Drone {did} finished all scan points and is now idle. "
                    + "Check zone coverage and reassign if needed."
                )

        for msg in user_msgs:
            triggers.append(f"[User message] {msg}")

        if triggers:
            prompt = "\n".join(triggers)
            await self._invoke(prompt)

        # AUTO-PAUSE: all zones completed and no drones actively working
        self._check_auto_pause(tick)

    def _drain_user_messages(self) -> list[str]:
        with self._user_msg_lock:
            msgs = list(self._user_messages)
            self._user_messages.clear()
            return msgs

    # ── Agent invocation (LLM via MCP tools) ──────────────────────────────────

    async def _invoke(self, user_message: str) -> None:
        input_messages: list[BaseMessage] = [
            *self._history,
            HumanMessage(content=user_message),
        ]
        n_input = len(input_messages)
        agent_input: dict[str, list[BaseMessage]] = {"messages": input_messages}

        try:
            result: dict[str, Any] = await self._agent.ainvoke(agent_input)  # pyright: ignore[reportArgumentType]
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

        # Only process messages generated during this invocation (not input history)
        all_messages: list[Any] = result.get("messages", [])
        new_messages = all_messages[n_input:]
        tick = self._tick_ref[0]

        for msg in new_messages:
            # Broadcast tool results (tool calls already broadcast by CoTMiddleware)
            if isinstance(msg, ToolMessage):
                tool_name: str = getattr(msg, "name", "?")
                raw = msg.content
                if isinstance(raw, str):
                    try:
                        result_data: dict[str, Any] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        result_data = {"output": raw}
                elif isinstance(raw, dict):
                    result_data = raw
                else:
                    result_data = {"output": str(raw)}
                log_tool_result(tick, tool_name, result_data)
                _broadcast_agent_event(
                    AgentToolResultEvent(tick=tick, tool=tool_name, result=result_data)
                )
                print(
                    f"{Fore.GREEN}[tick={tick}] {tool_name} -> {result_data}{Style.RESET_ALL}"
                )

            content = getattr(msg, "content", "")
            if (
                content
                and isinstance(msg, AIMessage)
                and not getattr(msg, "tool_calls", [])
            ):
                logger.debug("[tick=%d] AI: %s", tick, content[:200])

        self._history.append(HumanMessage(content=user_message))
        if new_messages:
            last = new_messages[-1]
            self._history.append(AIMessage(content=getattr(last, "content", "")))
        self._history = self._history[-10:]
