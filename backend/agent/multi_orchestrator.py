"""
Multi-Agent Orchestrator — Supervisor + Worker architecture.

The supervisor observes world state and delegates tasks to workers.
Each worker controls exactly one drone and reports results back.
All agents use the same LLM model, parallelized via asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import final

from colorama import Fore, Style

from agent.messages import TaskMessage, TaskResult
from agent.supervisor import SupervisorAgent
from agent.worker import DroneWorkerAgent
from world.engine import WorldEngine

logger = logging.getLogger("sar.multi_agent")


@final
class MultiAgentOrchestrator:
    """
    Coordinates supervisor and worker agents.

    Lifecycle:
      1. __init__: Create supervisor + workers, set up queues
      2. run(): Start all agents in parallel
      3. stop(): Gracefully shutdown all agents
    """

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

        # Communication queues
        self._task_queues: dict[str, asyncio.Queue[TaskMessage]] = {}
        self._result_queue: asyncio.Queue[TaskResult] = asyncio.Queue()

        # Create worker agents (one per drone)
        self._workers: dict[str, DroneWorkerAgent] = {}
        for drone_id in engine.list_drone_ids():
            task_queue: asyncio.Queue[TaskMessage] = asyncio.Queue()
            self._task_queues[drone_id] = task_queue
            self._workers[drone_id] = DroneWorkerAgent(
                engine=engine,
                drone_id=drone_id,
                task_queue=task_queue,
                result_queue=self._result_queue,
            )

        # Create supervisor agent
        self._supervisor = SupervisorAgent(
            engine=engine,
            mission=mission,
            base_col=base_col,
            base_row=base_row,
            task_queues=self._task_queues,
            result_queue=self._result_queue,
        )

        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

    async def run(self) -> None:
        """Start all agents in parallel."""
        self._running = True

        print(
            f"{Fore.MAGENTA}[MultiAgent] Starting supervisor + "
            + f"{len(self._workers)} workers{Style.RESET_ALL}"
        )
        logger.info(
            "MultiAgentOrchestrator starting: supervisor + %d workers",
            len(self._workers),
        )

        # Start workers
        for drone_id, worker in self._workers.items():
            task = asyncio.create_task(worker.run(), name=f"worker_{drone_id}")
            self._tasks.append(task)

        # Start supervisor
        supervisor_task = asyncio.create_task(self._supervisor.run(), name="supervisor")
        self._tasks.append(supervisor_task)

        # Add done callbacks for error logging
        for task in self._tasks:
            task.add_done_callback(self._on_task_done)

        # Wait for all tasks (they run until stopped)
        try:
            _ = await asyncio.gather(*self._tasks, return_exceptions=False)
        except asyncio.CancelledError:
            logger.info("MultiAgentOrchestrator cancelled")
        except Exception as exc:
            logger.error("Multi-agent task failed: %s", exc)
            raise

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        """Log when a task completes or fails."""
        name = task.get_name()
        if task.cancelled():
            logger.info("Task %s cancelled", name)
        elif exc := task.exception():
            tb = "".join(traceback.format_exception(exc))
            logger.error("Task %s died:\n%s", name, tb)
            print(f"{Fore.RED}[MultiAgent] Task {name} died: {exc}{Style.RESET_ALL}")

    def stop(self) -> None:
        """Stop all agents gracefully."""
        self._running = False

        print(f"{Fore.MAGENTA}[MultiAgent] Stopping all agents{Style.RESET_ALL}")
        logger.info("MultiAgentOrchestrator stopping")

        self._supervisor.stop()
        for worker in self._workers.values():
            worker.stop()
        for task in self._tasks:
            _ = task.cancel()

    def pause(self) -> None:
        """Pause the supervisor (workers continue current task)."""
        self._supervisor.pause()

    def unpause(self) -> None:
        """Resume the supervisor."""
        self._supervisor.unpause()

    def inject_user_message(self, message: str) -> None:
        """Queue a user message for the supervisor."""
        self._supervisor.inject_user_message(message)

    @property
    def is_paused(self) -> bool:
        return self._supervisor.is_paused
