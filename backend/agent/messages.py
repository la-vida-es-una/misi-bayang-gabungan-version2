"""
Inter-agent message types for Multi-LLM architecture.

These dataclasses define the communication protocol between
supervisor and worker agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """Status of a delegated task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskAction(str, Enum):
    """Available task actions for workers."""

    SCAN_CELL = "scan_cell"  # Move to cell, then thermal scan
    MOVE_TO = "move_to"  # Just move to cell
    RETURN_TO_BASE = "return_to_base"  # Return for charging


@dataclass
class TaskMessage:
    """Command from supervisor to worker."""

    task_id: str
    drone_id: str
    action: str  # TaskAction value as string for JSON compatibility
    params: dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # Higher = more urgent

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "drone_id": self.drone_id,
            "action": self.action,
            "params": self.params,
            "priority": self.priority,
        }


@dataclass
class TaskResult:
    """Result from worker to supervisor."""

    task_id: str
    drone_id: str
    status: TaskStatus
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "drone_id": self.drone_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class DroneStatusUpdate:
    """Periodic status update from worker (optional, for monitoring)."""

    drone_id: str
    col: int
    row: int
    battery: float
    status: str  # idle, moving, scanning, charging
    current_task_id: str | None = None
