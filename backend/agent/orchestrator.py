"""
Command Agent Orchestrator — LangChain 1.0 + Ollama (OpenAI-compat endpoint).

Uses the new create_agent API (LangGraph-backed, replaces AgentExecutor).
MCP tools are wrapped as LangChain @tool functions that call MCP HTTP internally.
CoT is captured via middleware before_model / after_model hooks.
Rolling 3-step window managed by agent/window.py.
World tick and agent tick are SEPARATE asyncio tasks.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
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
from agent.window import WindowManager

load_dotenv()
colorama_init(autoreset=True)

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://localhost:8000/mcp")
AGENT_TICK_SEC = float(os.getenv("AGENT_TICK_INTERVAL", "2.0"))

SYSTEM_PROMPT = """You are an autonomous SAR (Search and Rescue) Command Agent \
orchestrating a drone swarm in an offline disaster zone.

STRICT RULES — never violate:
1. ALWAYS call list_drones first if you do not know the active fleet.
2. ALWAYS call get_battery_status before assigning any route.
3. Battery <= 25% → immediately call move_to targeting base coordinates.
4. ALWAYS call thermal_scan after a drone arrives at a waypoint.
5. Survivors transition missing→found ONLY. No extraction.
6. Plan in windows of 3 waypoints per drone. Do not over-plan.
7. Never assume drone positions — verify with get_world_state.
8. Explain your reasoning step by step before every action."""


# ── CoT Middleware ────────────────────────────────────────────────────────────


class CoTMiddleware(AgentMiddleware):
    """Logs chain-of-thought before model calls and tool results after."""

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
                print(f"{Fore.YELLOW}[tick={tick}] 🧠 {content}{Style.RESET_ALL}")

    def after_model(self, state: AgentState, runtime: Any) -> None:  # type: ignore[override]
        tick = self._tick[0]
        messages = state.get("messages", [])
        if not messages:
            return
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", [])
        for tc in tool_calls:
            log_tool_call(tick, tc.get("name", "?"), tc.get("args", {}))
            print(
                f"{Fore.CYAN}[tick={tick}] 🔧 {tc.get('name')}({tc.get('args')}){Style.RESET_ALL}"
            )


# ── MCP HTTP helpers ──────────────────────────────────────────────────────────


async def _mcp_call_async(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{MCP_BASE_URL}/call",
            json={"tool": tool_name, "arguments": args},
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data


def _mcp_call_sync(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Sync wrapper — LangChain @tool functions run synchronously."""
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, _mcp_call_async(tool_name, args))
        result: dict[str, Any] = future.result(timeout=30)
        return result


# ── LangChain tool wrappers (call MCP HTTP internally) ────────────────────────


@tool
def move_to(drone_id: str, x: int, y: int) -> str:
    """
    Move a drone to cell (x, y). Queues a path; world engine walks it
    one cell per tick. Rejects out-of-polygon targets.

    Args:
        drone_id: ID of the drone to move.
        x: Target column (cell address).
        y: Target row (cell address).
    """
    return json.dumps(_mcp_call_sync("move_to", {"drone_id": drone_id, "x": x, "y": y}))


@tool
def get_battery_status(drone_id: str) -> str:
    """
    Return current battery percentage for a drone.

    Args:
        drone_id: ID of the drone to query.
    """
    return json.dumps(_mcp_call_sync("get_battery_status", {"drone_id": drone_id}))


@tool
def thermal_scan(drone_id: str) -> str:
    """
    Activate thermal sensor on a drone. Detects survivors within scan radius
    and transitions them from 'missing' to 'found'.

    Args:
        drone_id: ID of the scanning drone.
    """
    return json.dumps(_mcp_call_sync("thermal_scan", {"drone_id": drone_id}))


@tool
def get_world_state() -> str:
    """Return a full snapshot: all drone positions, battery, survivor statuses,
    grid bounds, and current tick."""
    return json.dumps(_mcp_call_sync("get_world_state", {}))


@tool
def list_drones() -> str:
    """Discover all active drone IDs on the network. Always call this first."""
    return json.dumps(_mcp_call_sync("list_drones", {}))


@tool
def get_pending_events() -> str:
    """Return and clear all world events since last poll: battery_low,
    survivor_found, drone_arrived, out_of_bounds_rejected."""
    return json.dumps(_mcp_call_sync("get_pending_events", {}))


ALL_TOOLS = [
    move_to,
    get_battery_status,
    thermal_scan,
    get_world_state,
    list_drones,
    get_pending_events,
]


# ── Command Agent ─────────────────────────────────────────────────────────────


class CommandAgent:
    def __init__(self, mission: str, base_col: int, base_row: int) -> None:
        self.mission = mission
        self.base_col = base_col
        self.base_row = base_row

        self._tick_ref: list[int] = [0]
        self._window = WindowManager()
        self._history: list[BaseMessage] = []
        self._running = False

        llm = ChatOpenAI(
            base_url=OLLAMA_BASE_URL,
            api_key=SecretStr("ollama"),  # Ollama ignores the value
            model=OLLAMA_MODEL,
            temperature=0,
        )

        self._agent = create_agent(
            llm,
            tools=ALL_TOOLS,
            system_prompt=SYSTEM_PROMPT,
            middleware=[CoTMiddleware(self._tick_ref)],
        )

    # ── Public entry ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        log_mission(f"Mission start: {self.mission}")
        print(f"{Fore.MAGENTA}📡 Mission: {self.mission}{Style.RESET_ALL}")

        await self._invoke(
            f"Mission: {self.mission}\n"
            f"Base is at cell ({self.base_col}, {self.base_row}).\n"
            "Begin by discovering the fleet and planning the first sweep."
        )

        while self._running:
            await asyncio.sleep(AGENT_TICK_SEC)
            await self._agent_tick()

    def stop(self) -> None:
        self._running = False

    # ── Per-tick reasoning ────────────────────────────────────────────────────

    async def _agent_tick(self) -> None:
        self._tick_ref[0] += 1
        tick = self._tick_ref[0]

        raw = _mcp_call_sync("get_pending_events", {})
        events: list[dict[str, Any]] = raw.get("events", [])

        messages: list[str] = []

        for ev in events:
            log_event(tick, ev)
            self._handle_event(ev)
            messages.append(f"[World event] {json.dumps(ev)}")

        for drone_id in self._window.drones_needing_replan():
            messages.append(
                f"[System] Drone {drone_id} has ≤1 waypoint remaining. "
                "Assign the next 3 waypoints for this drone now."
            )

        if not messages:
            return

        await self._invoke("\n".join(messages))

    def _handle_event(self, ev: dict[str, Any]) -> None:
        etype = ev.get("type")
        if etype == "drone_arrived":
            drone_id: str = ev["drone_id"]
            self._window.get(drone_id).consume(1)
        elif etype == "battery_low":
            drone_id = ev["drone_id"]
            self._window.get(drone_id).clear()

    # ── Agent invocation ──────────────────────────────────────────────────────

    async def _invoke(self, user_message: str) -> None:
        loop = asyncio.get_event_loop()

        # Build input as dict[str, list[BaseMessage]] — satisfies _InputAgentState
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
            print(f"{Fore.RED}[agent] executor error: {exc}{Style.RESET_ALL}")
            log_mission(f"Executor error: {exc}")
            return

        # Extract final AI message for history + window update
        out_messages: list[Any] = result.get("messages", [])

        for msg in out_messages:
            # Update rolling window from any move_to tool calls observed
            tool_calls = getattr(msg, "tool_calls", [])
            for tc in tool_calls:
                if tc.get("name") == "move_to":
                    args: dict[str, Any] = tc.get("args", {})
                    drone_id: str = args.get("drone_id", "")
                    x: int = args.get("x", 0)
                    y: int = args.get("y", 0)
                    self._window.get(drone_id).add_waypoints([(x, y)])
                    tick = self._tick_ref[0]
                    log_tool_result(tick, "move_to", args)
                    print(f"{Fore.GREEN}[tick={tick}] ✅ move_to {args}{Style.RESET_ALL}")

        # Append new turns to history, keep last 20 messages
        self._history.append(HumanMessage(content=user_message))
        if out_messages:
            last = out_messages[-1]
            self._history.append(AIMessage(content=getattr(last, "content", "")))
        self._history = self._history[-20:]
