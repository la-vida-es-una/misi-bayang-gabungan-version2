"""
World Engine — the ONLY place that mutates world state.

State machine (simplified for multi-zone):
  PENDING → RUNNING (start)
  RUNNING → ENDED   (explicit end call)

Zone lifecycle is per-zone, not global:
  idle → scanning → completed (or back to idle if stopped)

step() is a no-op unless phase == RUNNING.
Drone return-to-base is AI-reasoned — engine does NOT auto-recall.

Auto-scanning: When a drone is assigned to a zone via assign_coverage(),
the engine automatically performs thermal scans as the drone moves,
marking cells covered in the zone's mask. This eliminates the need for
the LLM to call thermal_scan() hundreds of times.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence
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
    MissionPhase,
    MissionResumedEvent,
    OutOfBoundsRejectedEvent,
    ScanStartedEvent,
    ScanStoppedEvent,
    Survivor,
    SurvivorFoundEvent,
    SurvivorStatus,
    WorldEvent,
    ZoneAddedEvent,
    ZoneCoveredEvent,
    ZoneRemovedEvent,
    ZoneStatus,
)

BATTERY_DRAIN_PER_MOVE = 0.5
BATTERY_CHARGE_PER_TICK = 2.0
BATTERY_LOW_THRESHOLD = 25.0
SCAN_RADIUS_CELLS = 5  # 11x11 detection pattern for faster coverage


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
        # Track which zones have already fired ZoneCoveredEvent
        self._zone_covered_fired: set[str] = set()

        # Auto-scan: drone_id → zone_id. Drones in this dict get automatic
        # thermal scans after every move during step().
        self._auto_scan_drones: dict[str, str] = {}

        # Per-consumer event buffers for drain_events()
        self._event_buffers: dict[str, list[WorldEvent]] = {}

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

    # ── Event buffer system ──────────────────────────────────────────────────

    def register_event_consumer(self, name: str) -> None:
        """Register a named event consumer (e.g. 'agent')."""
        with self._lock:
            if name not in self._event_buffers:
                self._event_buffers[name] = []

    def drain_events(self, name: str) -> list[WorldEvent]:
        """Return and clear all events for a named consumer."""
        with self._lock:
            buf = self._event_buffers.get(name)
            if buf is None:
                return []
            events = list(buf)
            buf.clear()
            return events

    def _push_to_buffers(self, events: Sequence[WorldEvent]) -> None:
        """Push events to all registered consumer buffers. Must hold _lock."""
        for buf in self._event_buffers.values():
            buf.extend(events)

    # ── Mission phase control ─────────────────────────────────────────────────

    def start(self) -> list[WorldEvent]:
        with self._lock:
            if self.phase != MissionPhase.PENDING:
                return []
            self.phase = MissionPhase.RUNNING
            events: list[WorldEvent] = [MissionResumedEvent()]
            self._push_to_buffers(events)
            return events

    def end(self) -> list[WorldEvent]:
        with self._lock:
            if self.phase == MissionPhase.ENDED:
                return []
            self.phase = MissionPhase.ENDED
            found = sum(
                1 for s in self._survivors.values() if s.status == SurvivorStatus.FOUND
            )
            total = len(self._survivors)
            completed = sum(
                1
                for z in self.grid.get_all_zones().values()
                if z.status == ZoneStatus.COMPLETED
            )
            events: list[WorldEvent] = [
                MissionEndedEvent(
                    survivors_found=found,
                    total_survivors=total,
                    zones_completed=completed,
                )
            ]
            self._push_to_buffers(events)
            return events

    # ── Zone lifecycle ────────────────────────────────────────────────────────

    def add_zone(
        self,
        zone_id: str,
        geojson_polygon: dict[str, object],
        label: str | None = None,
    ) -> list[WorldEvent]:
        """Register a new search zone on the grid."""
        with self._lock:
            zone = self.grid.add_zone(zone_id, geojson_polygon, label)
            events: list[WorldEvent] = [
                ZoneAddedEvent(
                    zone_id=zone.zone_id,
                    label=zone.label,
                    zone_cells=zone.total_cells,
                )
            ]
            self._push_to_buffers(events)
            return events

    def remove_zone(self, zone_id: str) -> list[WorldEvent]:
        """Remove a zone from the grid."""
        with self._lock:
            removed = self.grid.remove_zone(zone_id)
            if not removed:
                return []
            self._zone_covered_fired.discard(zone_id)
            events: list[WorldEvent] = [ZoneRemovedEvent(zone_id=zone_id)]
            self._push_to_buffers(events)
            return events

    def start_scan(self, zone_ids: list[str]) -> list[WorldEvent]:
        """Transition zones to SCANNING status."""
        with self._lock:
            started: list[str] = []
            for zid in zone_ids:
                zone = self.grid.get_zone(zid)
                if zone is None:
                    continue
                if zone.status == ZoneStatus.COMPLETED:
                    # Reset coverage for re-scan
                    zone.covered[:] = False
                    self._zone_covered_fired.discard(zid)
                zone.status = ZoneStatus.SCANNING
                started.append(zid)
            if not started:
                return []
            events: list[WorldEvent] = [ScanStartedEvent(zone_ids=started)]
            self._push_to_buffers(events)
            return events

    def stop_scan(self, zone_ids: list[str]) -> list[WorldEvent]:
        """Stop scanning zones (back to IDLE). Drones keep last command."""
        with self._lock:
            stopped: list[str] = []
            for zid in zone_ids:
                zone = self.grid.get_zone(zid)
                if zone is None:
                    continue
                if zone.status == ZoneStatus.SCANNING:
                    zone.status = ZoneStatus.IDLE
                    stopped.append(zid)
            if not stopped:
                return []
            events: list[WorldEvent] = [ScanStoppedEvent(zone_ids=stopped)]
            self._push_to_buffers(events)
            return events

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
            if events:
                self._push_to_buffers(events)
        return events

    def thermal_scan(self, drone_id: str) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        with self._lock:
            drone = self._drones.get(drone_id)
            if drone is None:
                return events
            drone.status = DroneStatus.SCANNING

            # Mark cells covered in ALL scanning zones
            scan_results = self.grid.mark_scanned(
                drone.col, drone.row, radius=SCAN_RADIUS_CELLS
            )

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

            # Check zone coverage for each scanning zone that got new coverage
            for zid, _newly in scan_results:
                if zid not in self._zone_covered_fired:
                    zone = self.grid.get_zone(zid)
                    if zone and zone.fully_covered:
                        self._zone_covered_fired.add(zid)
                        zone.status = ZoneStatus.COMPLETED
                        events.append(
                            ZoneCoveredEvent(
                                zone_id=zid,
                                total_cells=zone.total_cells,
                            )
                        )
            if events:
                self._push_to_buffers(events)
        return events

    # ── Coverage assignment & recall ──────────────────────────────────────────

    def assign_coverage(
        self, drone_id: str, waypoints: list[tuple[int, int]], zone_id: str
    ) -> dict[str, Any]:
        """
        Assign a coverage path to a drone and enable auto-scanning for a zone.

        Clears any existing path/assignment first. The drone will move through
        the waypoints one per tick, and the engine will automatically perform
        thermal scans at each position.
        """
        with self._lock:
            drone = self._drones.get(drone_id)
            if drone is None:
                return {"ok": False, "error": f"Unknown drone: {drone_id}"}

            # Clear existing path and assignment
            drone.path = []
            self._auto_scan_drones.pop(drone_id, None)

            # Validate waypoints
            valid: list[tuple[int, int]] = []
            for c, r in waypoints:
                if self.grid.in_bounds(c, r):
                    valid.append((c, r))

            if not valid:
                return {"ok": False, "error": "No valid waypoints in path"}

            drone.path = valid
            drone.status = DroneStatus.MOVING

            # Enable auto-scanning for this drone
            self._auto_scan_drones[drone_id] = zone_id

            return {"ok": True, "waypoints": len(valid)}

    def recall_drone(self, drone_id: str) -> dict[str, Any]:
        """
        Send a drone back to base for charging. Clears current path and
        auto-scan assignment, generates a return path via Bresenham line.
        """
        from agent.pathfinder import straight_line_path

        with self._lock:
            drone = self._drones.get(drone_id)
            if drone is None:
                return {"ok": False, "error": f"Unknown drone: {drone_id}"}

            # Clear current assignment
            drone.path = []
            self._auto_scan_drones.pop(drone_id, None)

            # Already at base?
            if drone.col == self.base_col and drone.row == self.base_row:
                drone.status = DroneStatus.IDLE
                return {"ok": True, "at_base": True, "return_path": 0}

            # Generate return path
            return_path = straight_line_path(
                drone.col, drone.row, self.base_col, self.base_row
            )
            # Filter for in-bounds cells
            valid = [(c, r) for c, r in return_path if self.grid.in_bounds(c, r)]
            # Ensure base is the final destination
            if not valid or valid[-1] != (self.base_col, self.base_row):
                valid.append((self.base_col, self.base_row))

            drone.path = valid
            drone.status = DroneStatus.MOVING

            est_battery = drone.battery - len(valid) * BATTERY_DRAIN_PER_MOVE
            return {
                "ok": True,
                "return_path": len(valid),
                "estimated_battery_on_arrival": round(max(0.0, est_battery), 1),
            }

    def get_drone_assignments(self) -> dict[str, str | None]:
        """Return drone_id → zone_id mapping for all drones."""
        with self._lock:
            return {did: self._auto_scan_drones.get(did) for did in self._drones}

    def _auto_scan(self, drone: Drone) -> list[WorldEvent]:
        """
        Perform automatic thermal scan at drone's current position.
        Called during step() for drones with auto-scan enabled.
        Marks cells as covered, detects survivors, checks zone completion.
        Must be called while holding self._lock.
        """
        events: list[WorldEvent] = []

        # Mark cells covered in all scanning zones
        scan_results = self.grid.mark_scanned(
            drone.col, drone.row, radius=SCAN_RADIUS_CELLS
        )

        # Detect survivors within scan radius
        for s in self._survivors.values():
            if s.status == SurvivorStatus.FOUND:
                continue
            dist = math.hypot(drone.col - s.col, drone.row - s.row)
            if dist <= SCAN_RADIUS_CELLS:
                s.status = SurvivorStatus.FOUND
                events.append(
                    SurvivorFoundEvent(
                        drone_id=drone.id,
                        survivor_id=s.id,
                        col=s.col,
                        row=s.row,
                    )
                )

        # Check zone coverage completion
        for zid, _newly in scan_results:
            if zid not in self._zone_covered_fired:
                zone = self.grid.get_zone(zid)
                if zone and zone.fully_covered:
                    self._zone_covered_fired.add(zid)
                    zone.status = ZoneStatus.COMPLETED
                    events.append(
                        ZoneCoveredEvent(
                            zone_id=zid,
                            total_cells=zone.total_cells,
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
            if events:
                self._push_to_buffers(events)
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

            # Auto-scan: if drone is assigned to a zone, scan at every position
            if drone.id in self._auto_scan_drones:
                scan_events = self._auto_scan(drone)
                events.extend(scan_events)

            if not drone.path:
                drone.status = DroneStatus.IDLE
                events.append(
                    DroneArrivedEvent(drone_id=drone.id, col=next_col, row=next_row)
                )
                # Clear auto-scan assignment when path completes
                self._auto_scan_drones.pop(drone.id, None)

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

    def get_zones(self) -> dict[str, dict]:
        """Return all zones with their status and coverage."""
        with self._lock:
            return {zid: z.to_dict() for zid, z in self.grid.get_all_zones().items()}

    def get_uncovered_cells(self, zone_id: str, max_cells: int = 10) -> list[dict]:
        """Return sample of uncovered cells in a zone for LLM guidance."""
        import random

        with self._lock:
            cells = self.grid.uncovered_zone_cells(zone_id)
            if len(cells) > max_cells:
                cells = random.sample(list(cells), max_cells)
            return [{"col": c, "row": r} for c, r in cells]

    def suggest_targets(self, zone_id: str, num_drones: int) -> list[dict]:
        """Suggest well-spaced target positions for multiple drones."""
        with self._lock:
            cells = list(self.grid.uncovered_zone_cells(zone_id))
            if not cells or num_drones <= 0:
                return []
            if len(cells) <= num_drones:
                return [
                    {"col": c, "row": r, "drone_index": i + 1}
                    for i, (c, r) in enumerate(cells)
                ]
            step = len(cells) // num_drones
            return [
                {
                    "col": cells[i * step][0],
                    "row": cells[i * step][1],
                    "drone_index": i + 1,
                }
                for i in range(num_drones)
            ]
