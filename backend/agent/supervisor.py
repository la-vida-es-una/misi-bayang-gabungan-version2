"""
Supervisor Agent — strategic coordinator for drone swarm.

Responsibilities:
  - Observe world state (drones, zones, coverage)
  - Delegate tasks to drone workers
  - Monitor task completion/failure
  - Does NOT directly control drones
"""

from __future__ import annotations

import asyncio
import json
import os
import traceback
import uuid
from typing import Any

from colorama import Fore, Style
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.agent import AgentState
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.cot_logger import log_mission, log_reasoning, log_tool_call, log_tool_result
from agent.messages import TaskMessage, TaskResult, TaskStatus
from world.engine import WorldEngine
from world.models import AgentThinkingEvent, AgentToolCallEvent, AgentToolResultEvent

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
SUPERVISOR_TICK_SEC = float(os.getenv("SUPERVISOR_TICK_INTERVAL", "2.0"))

SUPERVISOR_SYSTEM_PROMPT = """You are a drone swarm SUPERVISOR for search and rescue.

Your role is STRATEGIC COORDINATION only. You do NOT directly control drones.
Instead, you delegate tasks to drone workers and monitor their progress.

WORKFLOW:
1. Call list_drones() and get_zones() to understand the fleet and mission area.
2. If zones are "idle", they should already be started (auto-started on mission start).
3. Call suggest_targets(zone_id, num_drones) to get spaced-out targets.
4. For each target, call delegate_task() to assign a drone worker:
   - delegate_task(drone_id="drone_1", action="scan_cell", params={"x": 5, "y": 4})
   - Actions: "scan_cell" (move then thermal_scan), "return_to_base", "move_to"
5. Call get_task_results() to check on completed/failed tasks.
6. If a drone's battery is low (<=25%), delegate "return_to_base".

IMPORTANT:
- You CANNOT call move_to, thermal_scan, or get_battery_status directly.
- You MUST use delegate_task() to instruct drone workers.
- Assign different drones to DIFFERENT targets. Never stack them.
- Workers will report back when tasks complete or fail.
- Use the EXACT zone_id from get_zones() output (e.g., "default_zone").
"""


class CoTMiddleware(AgentMiddleware):
    """Logs supervisor reasoning and broadcasts to frontend."""

    def __init__(self, tick_ref: list[int]) -> None:
        self._tick = tick_ref

    def before_model(self, state: AgentState, runtime: Any) -> None:
        tick = self._tick[0]
        messages = state.get("messages", [])
        if messages:
            last = messages[-1]
            content = getattr(last, "content", "")
            if content:
                log_reasoning(tick, f"[supervisor] {content}")
                from mission.receiver import broadcast_event

                broadcast_event(AgentThinkingEvent(tick=tick, content=str(content)))

    def after_model(self, state: AgentState, runtime: Any) -> None:
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
            from mission.receiver import broadcast_event

            broadcast_event(AgentToolCallEvent(tick=tick, tool=name, args=args))


class SupervisorAgent:
    """Strategic supervisor that delegates tasks to workers."""

    def __init__(
        self,
        engine: WorldEngine,
        mission: str,
        base_col: int,
        base_row: int,
        task_queues: dict[str, asyncio.Queue[TaskMessage]],
        result_queue: asyncio.Queue[TaskResult],
    ) -> None:
        self.engine = engine
        self.mission = mission
        self.base_col = base_col
        self.base_row = base_row
        self._task_queues = task_queues
        self._result_queue = result_queue

        self._tick_ref: list[int] = [0]
        self._history: list[BaseMessage] = []
        self._running = False
        self._paused = False
        self._user_messages: list[str] = []

        # Pending tasks awaiting results
        self._pending_tasks: dict[str, TaskMessage] = {}

        # Build supervisor tools
        tools = self._build_tools()

        llm = ChatOpenAI(
            base_url=OLLAMA_BASE_URL,
            api_key=SecretStr("ollama"),
            model=OLLAMA_MODEL,
            temperature=0,
        )

        self._agent = create_agent(
            llm,
            tools=tools,
            system_prompt=SUPERVISOR_SYSTEM_PROMPT,
            middleware=[CoTMiddleware(self._tick_ref)],
        )

    def _build_tools(self) -> list:
        """Build supervisor-specific tools."""
        engine = self.engine
        task_queues = self._task_queues
        pending_tasks = self._pending_tasks
        base_col = self.base_col
        base_row = self.base_row
        result_queue = self._result_queue

        @tool
        def get_world_state() -> str:
            """Return full world snapshot: drones, survivors, zones, tick."""
            return json.dumps(engine.get_world_state())

        @tool
        def list_drones() -> str:
            """Discover all active drone IDs. Call this first."""
            ids = engine.list_drone_ids()
            return json.dumps({"ok": True, "drone_ids": ids, "count": len(ids)})

        @tool
        def get_zones() -> str:
            """Return all zones with status and coverage ratios."""
            zones = engine.get_zones()
            return json.dumps({"ok": True, "zones": zones, "count": len(zones)})

        @tool
        def suggest_targets(zone_id: str, num_drones: int) -> str:
            """Get well-spaced targets for multiple drones in a zone.

            Args:
                zone_id: The zone ID from get_zones() (e.g., "default_zone")
                num_drones: Number of drones to coordinate
            """
            targets = engine.suggest_targets(zone_id, num_drones)
            return json.dumps({"ok": True, "zone_id": zone_id, "targets": targets})

        @tool
        def get_uncovered_cells(zone_id: str) -> str:
            """Get sample of uncovered cells in a zone (max 10).

            Args:
                zone_id: The zone ID from get_zones()
            """
            cells = engine.get_uncovered_cells(zone_id, max_cells=10)
            total = len(engine.grid.uncovered_zone_cells(zone_id))
            return json.dumps(
                {
                    "ok": True,
                    "zone_id": zone_id,
                    "cells": cells,
                    "total_uncovered": total,
                }
            )

        @tool
        def delegate_task(
            drone_id: str, action: str, params: dict[str, Any] | None = None
        ) -> str:
            """
            Delegate a task to a drone worker.

            Args:
                drone_id: Which drone to task (e.g., "drone_1")
                action: One of "scan_cell", "move_to", "return_to_base"
                params: Action-specific parameters:
                  - scan_cell: {"x": int, "y": int} — move to cell, then thermal scan
                  - move_to: {"x": int, "y": int} — just move, no scan
                  - return_to_base: {} — return to base for charging
            """
            if drone_id not in task_queues:
                return json.dumps({"ok": False, "error": f"Unknown drone: {drone_id}"})

            params = params or {}

            # Handle return_to_base specially
            if action == "return_to_base":
                params = {"x": base_col, "y": base_row}
                action = "move_to"

            task_id = f"task_{uuid.uuid4().hex[:8]}"
            task = TaskMessage(
                task_id=task_id,
                drone_id=drone_id,
                action=action,
                params=params,
            )

            # Queue task for worker
            task_queues[drone_id].put_nowait(task)
            pending_tasks[task_id] = task

            return json.dumps(
                {
                    "ok": True,
                    "task_id": task_id,
                    "drone_id": drone_id,
                    "action": action,
                    "params": params,
                }
            )

        @tool
        def get_task_results() -> str:
            """
            Poll for completed task results from workers.
            Returns all results since last poll.
            """
            results = []
            while not result_queue.empty():
                try:
                    result = result_queue.get_nowait()
                    results.append(
                        {
                            "task_id": result.task_id,
                            "drone_id": result.drone_id,
                            "status": result.status.value,
                            "result": result.result,
                            "error": result.error,
                        }
                    )
                    # Remove from pending
                    pending_tasks.pop(result.task_id, None)
                except asyncio.QueueEmpty:
                    break

            pending_count = len(pending_tasks)
            return json.dumps(
                {
                    "ok": True,
                    "results": results,
                    "result_count": len(results),
                    "pending_count": pending_count,
                }
            )

        return [
            get_world_state,
            list_drones,
            get_zones,
            suggest_targets,
            get_uncovered_cells,
            delegate_task,
            get_task_results,
        ]

    async def run(self) -> None:
        """Main supervisor loop."""
        self._running = True
        log_mission(f"[Supervisor] Mission start: {self.mission}")
        print(f"{Fore.MAGENTA}[Supervisor] Mission: {self.mission}{Style.RESET_ALL}")

        # Initial prompt
        await self._invoke(
            f"Mission: {self.mission}\n"
            f"Base is at cell ({self.base_col}, {self.base_row}).\n"
            "Begin by discovering the fleet and checking zone statuses.\n"
            "Remember: Use delegate_task() to assign work to drone workers."
        )

        while self._running:
            await asyncio.sleep(SUPERVISOR_TICK_SEC)

            if self._paused:
                user_msgs = self._drain_user_messages()
                if user_msgs:
                    self._paused = False
                    for msg in user_msgs:
                        await self._invoke(f"[User message] {msg}")
                continue

            try:
                await self._supervisor_tick()
            except Exception as exc:
                tb = traceback.format_exc()
                print(
                    f"{Fore.RED}[Supervisor] Tick error: {exc}\n{tb}{Style.RESET_ALL}"
                )

    async def _supervisor_tick(self) -> None:
        """One reasoning cycle for the supervisor."""
        self._tick_ref[0] += 1
        tick = self._tick_ref[0]

        messages = []

        # Check for completed task results
        results = []
        while not self._result_queue.empty():
            try:
                result = self._result_queue.get_nowait()
                results.append(result)
                self._pending_tasks.pop(result.task_id, None)
            except asyncio.QueueEmpty:
                break

        if results:
            summary_parts = []
            for r in results:
                if r.status == TaskStatus.COMPLETED:
                    summary_parts.append(f"{r.drone_id} completed {r.task_id}")
                elif r.status == TaskStatus.FAILED:
                    summary_parts.append(f"{r.drone_id} FAILED {r.task_id}: {r.error}")
            messages.append(f"[Task results] {'; '.join(summary_parts)}")

        # Check for user messages
        user_msgs = self._drain_user_messages()
        for msg in user_msgs:
            messages.append(f"[User message] {msg}")

        # Periodic status check (every 5 ticks)
        if tick % 5 == 0:
            messages.append(
                "[System] Check zone coverage and pending tasks. "
                "If no tasks pending, assign new targets."
            )

        if messages:
            await self._invoke("\n".join(messages))

    async def _invoke(self, user_message: str) -> None:
        """Invoke the LLM agent."""
        loop = asyncio.get_running_loop()
        tick = self._tick_ref[0]

        input_messages: list[BaseMessage] = [
            *self._history,
            HumanMessage(content=user_message),
        ]
        agent_input: dict[str, list[BaseMessage]] = {"messages": input_messages}

        log_reasoning(tick, f"[Supervisor input] {user_message[:200]}")
        print(f"{Fore.YELLOW}[Supervisor tick={tick}] {user_message}{Style.RESET_ALL}")

        try:
            result: dict[str, Any] = await loop.run_in_executor(
                None, lambda: self._agent.invoke(agent_input)
            )
        except Exception as exc:
            tb = traceback.format_exc()
            print(f"{Fore.RED}[Supervisor] Invoke error: {exc}\n{tb}{Style.RESET_ALL}")
            return

        # Extract messages from result
        out_messages: list[Any] = result.get("messages", [])

        for msg in out_messages:
            tool_calls = getattr(msg, "tool_calls", [])
            for tc in tool_calls:
                name: str = tc.get("name", "?")
                args: dict[str, Any] = tc.get("args", {})
                log_tool_call(tick, name, args)
                print(f"{Fore.CYAN}[Supervisor] {name}({args}){Style.RESET_ALL}")

        # Update history (keep last 10 messages)
        self._history.append(HumanMessage(content=user_message))
        if out_messages:
            last = out_messages[-1]
            self._history.append(AIMessage(content=getattr(last, "content", "")))
        self._history = self._history[-10:]

    def _drain_user_messages(self) -> list[str]:
        msgs = list(self._user_messages)
        self._user_messages.clear()
        return msgs

    def stop(self) -> None:
        self._running = False

    def pause(self) -> None:
        self._paused = True

    def unpause(self) -> None:
        self._paused = False

    def inject_user_message(self, message: str) -> None:
        self._user_messages.append(message)

    @property
    def is_paused(self) -> bool:
        return self._paused
