"""
Drone Worker Agent — executes tasks for a single drone.

Each worker:
  - Controls exactly ONE drone
  - Receives tasks from supervisor via queue
  - Executes tasks using drone-scoped tools
  - Reports results back to supervisor
"""

from __future__ import annotations

import asyncio
import json
import os
import traceback
from dataclasses import asdict
from typing import final

from colorama import Fore, Style
from langchain.agents import create_agent  # pyright: ignore[reportUnknownVariableType]
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool  # pyright: ignore[reportUnknownVariableType]
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.messages import TaskMessage, TaskResult, TaskStatus
from agent.pathfinder import straight_line_path
from world.engine import WorldEngine

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

WORKER_SYSTEM_PROMPT = """You are a drone worker controlling drone {drone_id}.

You receive tasks from the supervisor and execute them.
You can ONLY control YOUR drone — you cannot affect other drones.

TASK TYPES:
1. "scan_cell" — Move to cell (x, y), then run thermal_scan()
2. "move_to" — Just move to cell (x, y)

WORKFLOW:
1. Receive task with action and params
2. Execute using your tools: move_to(x, y) and thermal_scan()
3. Call report_complete() when done, or report_error() if something fails

IMPORTANT:
- Check battery before moves
- Report completion/errors promptly
- You do NOT decide strategy — just execute tasks
"""


@final
class DroneWorkerAgent:
    """Worker agent that controls a single drone."""

    def __init__(
        self,
        engine: WorldEngine,
        drone_id: str,
        task_queue: asyncio.Queue[TaskMessage],
        result_queue: asyncio.Queue[TaskResult],
    ) -> None:
        self.engine = engine
        self.drone_id = drone_id
        self._task_queue = task_queue
        self._result_queue = result_queue

        self._running = False
        self._current_task: TaskMessage | None = None
        self._task_completed = False
        self._task_error: str | None = None

        # Build drone-scoped tools
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
            system_prompt=WORKER_SYSTEM_PROMPT.format(drone_id=drone_id),
        )

    def _build_tools(self) -> list:  # pyright: ignore[reportMissingTypeArgument]
        """Build tools scoped to this drone only."""
        engine = self.engine
        drone_id = self.drone_id
        worker = self  # Reference for completion reporting

        @tool
        def move_to(x: int, y: int) -> str:
            """
            Move this drone to cell (x, y).

            Args:
                x: Target column
                y: Target row
            """
            state = engine.get_world_state()
            drone_state = state["drones"].get(drone_id)
            if drone_state is None:
                return json.dumps({"ok": False, "error": f"Drone {drone_id} not found"})

            # Validate bounds
            bounds = engine.grid.bounds
            if not (0 <= x < bounds["cols"] and 0 <= y < bounds["rows"]):
                return json.dumps({"ok": False, "error": f"Out of bounds: ({x}, {y})"})

            path = straight_line_path(drone_state["col"], drone_state["row"], x, y)
            engine.assign_path(drone_id, path)

            return json.dumps(
                {
                    "ok": True,
                    "drone_id": drone_id,
                    "target": {"x": x, "y": y},
                    "path_length": len(path),
                }
            )

        @tool
        def thermal_scan() -> str:
            """Activate thermal sensor on this drone."""
            events = engine.thermal_scan(drone_id)
            found = [
                asdict(e)
                for e in events
                if getattr(e, "type", None) == "survivor_found"
            ]
            return json.dumps(
                {
                    "ok": True,
                    "drone_id": drone_id,
                    "survivors_found": len(found),
                }
            )

        @tool
        def get_battery_status() -> str:
            """Get current battery level for this drone."""
            battery = engine.get_battery(drone_id)
            if battery is None:
                return json.dumps({"ok": False, "error": "Battery read failed"})
            return json.dumps(
                {
                    "ok": True,
                    "drone_id": drone_id,
                    "battery": round(battery, 2),
                }
            )

        @tool
        def get_position() -> str:
            """Get current position of this drone."""
            state = engine.get_world_state()
            drone_state = state["drones"].get(drone_id)
            if drone_state is None:
                return json.dumps({"ok": False, "error": "Position read failed"})
            return json.dumps(
                {
                    "ok": True,
                    "drone_id": drone_id,
                    "col": drone_state["col"],
                    "row": drone_state["row"],
                    "status": drone_state["status"],
                    "path_remaining": drone_state["path_remaining"],
                }
            )

        @tool
        def report_complete(message: str = "") -> str:
            """
            Report that the current task is complete.

            Args:
                message: Optional completion message
            """
            worker._task_completed = True
            return json.dumps({"ok": True, "status": "completed", "message": message})

        @tool
        def report_error(error: str) -> str:
            """
            Report that the current task failed.

            Args:
                error: Error description
            """
            worker._task_error = error
            return json.dumps({"ok": True, "status": "error", "error": error})

        return [
            move_to,
            thermal_scan,
            get_battery_status,
            get_position,
            report_complete,
            report_error,
        ]

    async def run(self) -> None:
        """Main worker loop — wait for tasks, execute, report."""
        self._running = True
        print(f"{Fore.BLUE}[Worker {self.drone_id}] Started{Style.RESET_ALL}")

        while self._running:
            try:
                # Wait for next task (with timeout to allow stop checking)
                task = await asyncio.wait_for(self._task_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Execute task
            await self._execute_task(task)

        print(f"{Fore.BLUE}[Worker {self.drone_id}] Stopped{Style.RESET_ALL}")

    async def _execute_task(self, task: TaskMessage) -> None:
        """Execute a single task and report result."""
        self._current_task = task
        self._task_completed = False
        self._task_error = None

        print(
            f"{Fore.CYAN}[Worker {self.drone_id}] "
            f"Executing {task.action} {task.params}{Style.RESET_ALL}"
        )

        # Format task as prompt for the worker LLM
        prompt = self._task_to_prompt(task)

        try:
            # Run agent to execute task
            await self._invoke(prompt)

            # Wait for movement to complete (poll position)
            if task.action in ("scan_cell", "move_to"):
                await self._wait_for_arrival()

            # If scan_cell, also do thermal scan after arrival
            if task.action == "scan_cell" and not self._task_error:
                self.engine.thermal_scan(self.drone_id)

            # Create result
            if self._task_error:
                result = TaskResult(
                    task_id=task.task_id,
                    drone_id=self.drone_id,
                    status=TaskStatus.FAILED,
                    error=self._task_error,
                )
            else:
                result = TaskResult(
                    task_id=task.task_id,
                    drone_id=self.drone_id,
                    status=TaskStatus.COMPLETED,
                    result={"action": task.action, "params": task.params},
                )

            # Send result to supervisor
            await self._result_queue.put(result)
            print(
                f"{Fore.GREEN}[Worker {self.drone_id}] "
                f"Task {task.task_id} -> {result.status.value}{Style.RESET_ALL}"
            )

        except Exception as e:
            tb = traceback.format_exc()
            print(
                f"{Fore.RED}[Worker {self.drone_id}] Error: {e}\n{tb}{Style.RESET_ALL}"
            )
            result = TaskResult(
                task_id=task.task_id,
                drone_id=self.drone_id,
                status=TaskStatus.FAILED,
                error=str(e),
            )
            await self._result_queue.put(result)

        self._current_task = None

    def _task_to_prompt(self, task: TaskMessage) -> str:
        """Convert task message to LLM prompt."""
        if task.action == "scan_cell":
            x, y = task.params.get("x", 0), task.params.get("y", 0)
            return (
                f"Task {task.task_id}: Scan cell ({x}, {y}).\n"
                f"1. Call move_to({x}, {y})\n"
                f"2. Wait for arrival\n"
                f"3. Call thermal_scan()\n"
                f"4. Call report_complete()"
            )
        elif task.action == "move_to":
            x, y = task.params.get("x", 0), task.params.get("y", 0)
            return (
                f"Task {task.task_id}: Move to cell ({x}, {y}).\n"
                f"1. Call move_to({x}, {y})\n"
                f"2. Call report_complete() when done"
            )
        else:
            return f"Task {task.task_id}: Unknown action {task.action}. Call report_error()."

    async def _wait_for_arrival(self, timeout: float = 60.0) -> None:
        """Wait for drone to arrive at target (poll path_remaining)."""
        waited = 0.0
        interval = 0.5

        while waited < timeout:
            state = self.engine.get_world_state()
            drone_state = state["drones"].get(self.drone_id)

            if drone_state and drone_state["path_remaining"] == 0:
                return

            await asyncio.sleep(interval)
            waited += interval

        self._task_error = "Timeout waiting for arrival"

    async def _invoke(self, user_message: str) -> None:
        """Invoke the worker LLM."""
        loop = asyncio.get_running_loop()
        input_messages = [HumanMessage(content=user_message)]

        try:
            await loop.run_in_executor(
                None, lambda: self._agent.invoke({"messages": input_messages})
            )
        except Exception as e:
            self._task_error = str(e)

    def stop(self) -> None:
        """Stop the worker."""
        self._running = False
