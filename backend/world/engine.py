"""
World Engine — the ONLY place that mutates world state.

State machine:
  PENDING → RUNNING (start/resume)
  RUNNING → PAUSED  (zone covered + all drones at base)
  PAUSED  → RUNNING (new zone submitted + resume called)
  RUNNING → ENDED   (explicit end call)
  PAUSED  → ENDED   (explicit end call)

step() is a no-op unless phase == RUNNING.
"""

from __future__ import annotations

import math
import threading
from typing import Any

from world.grid import Grid
from world.models import (
    BatteryLowEvent,
    Drone,
    DroneArrivedEvent,
    DroneChargingEvent,
    DroneMovedEvent,
    DroneStatus,
    MissionEndedEvent,
    MissionPausedEvent,
    MissionPhase,
    MissionResumedEvent,
    OutOfBoundsRejectedEvent,
    Survivor,
    SurvivorFoundEvent,
    SurvivorStatus,
    WorldEvent,
    ZoneCoveredEvent,
)

BATTERY_DRAIN_PER_MOVE = 0.5
BATTERY_CHARGE_PER_TICK = 2.0
BATTERY_LOW_THRESHOLD = 25.0
SCAN_RADIUS_CELLS = 2


class WorldEngine:
    def __init__(self, grid: Grid, base_col: int, base_row: int) -> None:
        self.grid = grid
        self.base_col = base_col
        self.base_row = base_row
        self.phase = MissionPhase.PENDING

        self._drones: dict[str, Drone] = {}
        self._survivors: dict[str, Survivor] = {}
        self._tick: int = 0

        self._low_battery_fired: set[str] = set()
        self._zone_covered_fired: bool = False  # reset each new zone

        self._lock = threading.Lock()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def add_drone(self, drone_id: str) -> None:
        with self._lock:
            self._drones[drone_id] = Drone(
                id=drone_id,
                col=self.base_col,
                row=self.base_row,
            )

    def add_survivor(self, survivor_id: str, col: int, row: int) -> None:
        with self._lock:
            self._survivors[survivor_id] = Survivor(id=survivor_id, col=col, row=row)

    # ── Mission phase control ─────────────────────────────────────────────────

    def start(self) -> list[WorldEvent]:
        with self._lock:
            if self.phase not in (MissionPhase.PENDING, MissionPhase.PAUSED):
                return []
            self.phase = MissionPhase.RUNNING
            self._zone_covered_fired = False
            return [MissionResumedEvent(zone_index=self.grid.zone_index)]

    def end(self) -> list[WorldEvent]:
        with self._lock:
            if self.phase == MissionPhase.ENDED:
                return []
            self.phase = MissionPhase.ENDED
            found = sum(
                1 for s in self._survivors.values() if s.status == SurvivorStatus.FOUND
            )
            total = len(self._survivors)
            return [
                MissionEndedEvent(
                    survivors_found=found,
                    total_survivors=total,
                    zones_completed=self.grid.zone_index,
                )
            ]

    # ── MCP action entry points ───────────────────────────────────────────────

    def assign_path(
        self, drone_id: str, waypoints: list[tuple[int, int]]
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        with self._lock:
            drone = self._drones.get(drone_id)
            if drone is None:
                return events
            valid: list[tuple[int, int]] = []
            for col, row in waypoints:
                if self.grid.in_bounds(col, row):
                    valid.append((col, row))
                else:
                    events.append(
                        OutOfBoundsRejectedEvent(drone_id=drone_id, col=col, row=row)
                    )
            if valid:
                drone.path.extend(valid)
                drone.status = DroneStatus.MOVING
        return events

    def thermal_scan(self, drone_id: str) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        with self._lock:
            drone = self._drones.get(drone_id)
            if drone is None:
                return events
            drone.status = DroneStatus.SCANNING

            # Mark cells covered (2-cell radius = 5×5 area)
            self.grid.mark_scanned(drone.col, drone.row, radius=SCAN_RADIUS_CELLS)

            # Detect survivors
            for s in self._survivors.values():
                if s.status == SurvivorStatus.FOUND:
                    continue
                dist = math.hypot(drone.col - s.col, drone.row - s.row)
                if dist <= SCAN_RADIUS_CELLS:
                    s.status = SurvivorStatus.FOUND
                    events.append(
                        SurvivorFoundEvent(
                            drone_id=drone_id,
                            survivor_id=s.id,
                            col=s.col,
                            row=s.row,
                        )
                    )

            # Check zone coverage
            if not self._zone_covered_fired and self.grid.zone_fully_covered():
                self._zone_covered_fired = True
                events.append(
                    ZoneCoveredEvent(
                        zone_index=self.grid.zone_index,
                        total_cells=len(self.grid.all_zone_cells()),
                    )
                )
        return events

    # ── World tick ────────────────────────────────────────────────────────────

    def step(self) -> list[WorldEvent]:
        """Advance world by 1 tick. No-op unless RUNNING."""
        events: list[WorldEvent] = []
        with self._lock:
            if self.phase != MissionPhase.RUNNING:
                return events
            self._tick += 1
            for drone in self._drones.values():
                events.extend(self._tick_drone(drone))

            # Auto-pause: zone covered AND all drones at base
            if self._zone_covered_fired and self._all_drones_at_base():
                self.phase = MissionPhase.PAUSED
                events.append(MissionPausedEvent(zone_index=self.grid.zone_index))
        return events

    def _tick_drone(self, drone: Drone) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        at_base = drone.col == self.base_col and drone.row == self.base_row

        # Charging
        if at_base and drone.battery < 100.0 and not drone.path:
            drone.status = DroneStatus.CHARGING
            drone.battery = min(100.0, drone.battery + BATTERY_CHARGE_PER_TICK)
            if drone.battery >= 100.0:
                drone.battery = 100.0
                drone.status = DroneStatus.IDLE
                self._low_battery_fired.discard(drone.id)
            events.append(DroneChargingEvent(drone_id=drone.id, battery=drone.battery))
            return events

        # Move one cell along path
        if drone.path:
            prev_col, prev_row = drone.col, drone.row
            next_col, next_row = drone.path.pop(0)
            drone.col = next_col
            drone.row = next_row
            drone.battery = max(0.0, drone.battery - BATTERY_DRAIN_PER_MOVE)
            drone.status = DroneStatus.MOVING

            events.append(
                DroneMovedEvent(
                    drone_id=drone.id,
                    from_col=prev_col,
                    from_row=prev_row,
                    to_col=next_col,
                    to_row=next_row,
                )
            )

            if not drone.path:
                drone.status = DroneStatus.IDLE
                events.append(
                    DroneArrivedEvent(drone_id=drone.id, col=next_col, row=next_row)
                )

            if (
                drone.battery <= BATTERY_LOW_THRESHOLD
                and drone.id not in self._low_battery_fired
            ):
                self._low_battery_fired.add(drone.id)
                events.append(BatteryLowEvent(drone_id=drone.id, battery=drone.battery))

        return events

    # ── Read-only queries ─────────────────────────────────────────────────────

    def get_battery(self, drone_id: str) -> float | None:
        with self._lock:
            d = self._drones.get(drone_id)
            return d.battery if d else None

    def get_world_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tick": self._tick,
                "phase": self.phase.value,
                "grid": self.grid.bounds,
                "base": {"col": self.base_col, "row": self.base_row},
                "drones": {
                    did: {
                        "col": d.col,
                        "row": d.row,
                        "lat": self.grid.cell_to_geo(d.col, d.row)[1],
                        "lon": self.grid.cell_to_geo(d.col, d.row)[0],
                        "battery": round(d.battery, 2),
                        "status": d.status.value,
                        "path_remaining": len(d.path),
                    }
                    for did, d in self._drones.items()
                },
                "survivors": {
                    sid: {
                        "col": s.col,
                        "row": s.row,
                        "lat": self.grid.cell_to_geo(s.col, s.row)[1],
                        "lon": self.grid.cell_to_geo(s.col, s.row)[0],
                        "status": s.status.value,
                    }
                    for sid, s in self._survivors.items()
                },
            }

    def list_drone_ids(self) -> list[str]:
        with self._lock:
            return list(self._drones.keys())

    # ── Private helpers ───────────────────────────────────────────────────────

    def _all_drones_at_base(self) -> bool:
        return all(
            d.col == self.base_col and d.row == self.base_row and not d.path
            for d in self._drones.values()
        )
