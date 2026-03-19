"""
Rolling 3-step planning window per drone.

Rules:
  - Each drone always has up to 3 future waypoints assigned.
  - When path_remaining <= 1, the orchestrator must replan for that drone.
  - Window tracks what the LLM has *planned*, not what the engine has walked.
    The engine is the source of truth for position; window is for replan triggers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WINDOW_SIZE = 3  # total waypoints in window
REPLAN_THRESHOLD = 1  # replan when remaining waypoints ≤ this


@dataclass
class DroneWindow:
    drone_id: str
    planned: list[tuple[int, int]] = field(default_factory=list)

    def add_waypoints(self, waypoints: list[tuple[int, int]]) -> None:
        """Append waypoints, capped at WINDOW_SIZE."""
        self.planned.extend(waypoints)
        self.planned = self.planned[:WINDOW_SIZE]

    def consume(self, n: int = 1) -> None:
        """Mark n waypoints as consumed (called when DroneArrivedEvent fires)."""
        self.planned = self.planned[n:]

    @property
    def needs_replan(self) -> bool:
        return len(self.planned) <= REPLAN_THRESHOLD

    @property
    def remaining(self) -> int:
        return len(self.planned)

    def clear(self) -> None:
        self.planned.clear()


class WindowManager:
    def __init__(self) -> None:
        self._windows: dict[str, DroneWindow] = {}

    def register(self, drone_id: str) -> None:
        self._windows[drone_id] = DroneWindow(drone_id=drone_id)

    def get(self, drone_id: str) -> DroneWindow:
        if drone_id not in self._windows:
            self.register(drone_id)
        return self._windows[drone_id]

    def drones_needing_replan(self) -> list[str]:
        return [did for did, w in self._windows.items() if w.needs_replan]

    def all_ids(self) -> list[str]:
        return list(self._windows.keys())
