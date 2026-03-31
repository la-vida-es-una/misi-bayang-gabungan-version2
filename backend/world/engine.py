"""
World Engine — the ONLY place that mutates world state.

State machine (simplified for multi-zone):
  PENDING → RUNNING (start)
  RUNNING → ENDED   (explicit end call)

Zone lifecycle is per-zone, not global:
  idle → scanning → completed (or back to idle if stopped)

step() is a no-op unless phase == RUNNING.
Drone return-to-base is AI-reasoned — engine does NOT auto-recall.

Drones are autonomous: when a drone arrives at a scan waypoint and has
entries in its scan queue, the engine auto-scans and advances to the
next waypoint inline within _tick_drone().  MCP tools (thermal_scan,
move_to) remain exposed for study-case compliance but the hot path
no longer round-trips through the agent.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any, final

import numpy as np

from world.grid import Grid
from world.models import (
    BatteryLowEvent,
    Drone,
    DroneArrivedEvent,
    DroneChargingEvent,
    DroneMovedEvent,
    DroneScannedEvent,
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

BATTERY_DRAIN_PER_MOVE = 1.0
BATTERY_CHARGE_PER_TICK = 2.0
BATTERY_LOW_THRESHOLD = 25.0
BATTERY_IDLE_DRAIN_PER_TICK = 0.1  # Slow drain for idle drones not at base
SCAN_RADIUS_CELLS = 3  # 7x7 detection pattern for tighter coverage


@final
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

        # Zone assignment: drone_id → zone_id (which zone is the drone covering?)
        self._drone_zone: dict[str, str] = {}

        # Scan queue: drone_id → list of (segment, scan_point) pairs remaining.
        # When a drone finishes a segment (DroneArrivedEvent), the orchestrator
        # pops the next entry, calls thermal_scan via MCP, then assigns the
        # next segment via move_to/assign_path.
        self._drone_scan_queue: dict[
            str, list[tuple[list[tuple[int, int]], tuple[int, int]]]
        ] = {}

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

    def inject_event(self, event: WorldEvent) -> None:
        """Push a synthetic event into all consumer buffers."""
        with self._lock:
            self._push_to_buffers([event])

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

    def _do_thermal_scan(
        self, drone_id: str
    ) -> tuple[list[WorldEvent], dict[str, Any]]:
        """Core scan logic (must hold _lock). Returns (events, result_dict)."""
        events: list[WorldEvent] = []
        drone = self._drones.get(drone_id)
        if drone is None:
            return events, {"covered_new": 0, "survivors_found": [], "zone_coverages": {}}

        drone.status = DroneStatus.SCANNING

        # Mark cells covered in ALL scanning zones
        scan_results = self.grid.mark_scanned(
            drone.col, drone.row, radius=SCAN_RADIUS_CELLS
        )

        # Detect survivors (square pattern, same as coverage marking)
        survivors_found: list[str] = []
        for s in self._survivors.values():
            if s.status == SurvivorStatus.FOUND:
                continue
            if (
                abs(drone.col - s.col) <= SCAN_RADIUS_CELLS
                and abs(drone.row - s.row) <= SCAN_RADIUS_CELLS
            ):
                s.status = SurvivorStatus.FOUND
                survivors_found.append(s.id)
                events.append(
                    SurvivorFoundEvent(
                        drone_id=drone_id,
                        survivor_id=s.id,
                        col=s.col,
                        row=s.row,
                    )
                )

        # Check zone coverage for each scanning zone that got new coverage
        zone_coverages: dict[str, float] = {}
        covered_new = 0
        for zid, newly in scan_results:
            covered_new += len(newly)
            zone = self.grid.get_zone(zid)
            if zone:
                zone_coverages[zid] = zone.coverage_ratio
            if zid not in self._zone_covered_fired:
                if zone and zone.fully_covered:
                    self._zone_covered_fired.add(zid)
                    zone.status = ZoneStatus.COMPLETED
                    events.append(
                        ZoneCoveredEvent(
                            zone_id=zid,
                            total_cells=zone.total_cells,
                        )
                    )

        return events, {
            "covered_new": covered_new,
            "survivors_found": survivors_found,
            "zone_coverages": zone_coverages,
        }

    def thermal_scan(self, drone_id: str) -> list[WorldEvent]:
        """Public MCP entry point — delegates to _do_thermal_scan."""
        with self._lock:
            events, _result = self._do_thermal_scan(drone_id)
            if events:
                self._push_to_buffers(events)
        return events

    # ── Coverage assignment & recall ──────────────────────────────────────────

    def set_drone_zone(self, drone_id: str, zone_id: str | None) -> None:
        """Track which zone a drone is currently assigned to."""
        with self._lock:
            if zone_id is None:
                _ = self._drone_zone.pop(drone_id, None)
            else:
                self._drone_zone[drone_id] = zone_id

    def set_scan_queue(
        self,
        drone_id: str,
        queue: list[tuple[list[tuple[int, int]], tuple[int, int]]],
    ) -> None:
        """Store a queue of (segment, scan_point) pairs for a drone.

        The orchestrator pops entries one by one: assigns the segment as
        a path, waits for DroneArrivedEvent, calls thermal_scan via MCP,
        then pops the next entry.
        """
        with self._lock:
            self._drone_scan_queue[drone_id] = list(queue)

    def pop_scan_queue(
        self, drone_id: str
    ) -> tuple[list[tuple[int, int]], tuple[int, int]] | None:
        """Pop and return the next (segment, scan_point) from the queue."""
        with self._lock:
            q = self._drone_scan_queue.get(drone_id)
            if q:
                return q.pop(0)
            return None

    def peek_scan_queue(self, drone_id: str) -> int:
        """Return number of scan points remaining in queue."""
        with self._lock:
            return len(self._drone_scan_queue.get(drone_id, []))

    def _peek_scan_queue_entry(
        self, drone_id: str
    ) -> tuple[list[tuple[int, int]], tuple[int, int]] | None:
        """Return next (segment, scan_point) without popping. Must hold _lock."""
        q = self._drone_scan_queue.get(drone_id)
        if q:
            return q[0]
        return None

    def _pop_scan_queue_locked(
        self, drone_id: str
    ) -> tuple[list[tuple[int, int]], tuple[int, int]] | None:
        """Pop next entry. Must hold _lock."""
        q = self._drone_scan_queue.get(drone_id)
        if q:
            return q.pop(0)
        return None

    def push_scan_queue_entry(
        self,
        drone_id: str,
        entry: tuple[list[tuple[int, int]], tuple[int, int]],
        front: bool = False,
    ) -> None:
        """Insert an entry into a drone's scan queue."""
        with self._lock:
            q = self._drone_scan_queue.setdefault(drone_id, [])
            if front:
                q.insert(0, entry)
            else:
                q.append(entry)

    def clear_drone_assignment(self, drone_id: str) -> None:
        """Clear zone assignment, scan queue, and reset drone to IDLE."""
        with self._lock:
            _ = self._drone_zone.pop(drone_id, None)
            _ = self._drone_scan_queue.pop(drone_id, None)
            drone = self._drones.get(drone_id)
            if drone is not None and drone.status == DroneStatus.SCANNING:
                drone.status = DroneStatus.IDLE

    def recall_drone(self, drone_id: str) -> dict[str, Any]:
        """
        Send a drone back to base for charging.  Clears current path,
        zone assignment, and scan queue.  Generates a return path.
        """
        from agent.pathfinder import straight_line_path

        with self._lock:
            drone = self._drones.get(drone_id)
            if drone is None:
                return {"ok": False, "error": f"Unknown drone: {drone_id}"}

            # Clear everything
            drone.path = []
            _ = self._drone_zone.pop(drone_id, None)
            _ = self._drone_scan_queue.pop(drone_id, None)

            if drone.col == self.base_col and drone.row == self.base_row:
                drone.status = DroneStatus.IDLE
                return {"ok": True, "at_base": True, "return_path": 0}

            return_path = straight_line_path(
                drone.col, drone.row, self.base_col, self.base_row
            )
            valid = [(c, r) for c, r in return_path if self.grid.in_bounds(c, r)]
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
            return {did: self._drone_zone.get(did) for did in self._drones}

    def get_claimed_mask(
        self, zone_id: str, exclude_drone: str | None = None
    ) -> np.ndarray | None:
        """Build a bool mask of cells claimed by other drones' scan queues.

        Returns a (rows, cols) bool array where True = another drone is
        planning to scan that cell.  Returns None if the zone doesn't exist.
        """
        with self._lock:
            zone = self.grid.get_zone(zone_id)
            if zone is None:
                return None
            rows, cols = zone.mask.shape
            claimed = np.zeros((rows, cols), dtype=bool)
            for did, assigned_zone in self._drone_zone.items():
                if assigned_zone != zone_id:
                    continue
                if did == exclude_drone:
                    continue
                q = self._drone_scan_queue.get(did, [])
                drone = self._drones.get(did)
                # Mark cells around each queued scan point
                for _seg, sp in q:
                    for dc in range(-SCAN_RADIUS_CELLS, SCAN_RADIUS_CELLS + 1):
                        for dr in range(-SCAN_RADIUS_CELLS, SCAN_RADIUS_CELLS + 1):
                            c, r = sp[0] + dc, sp[1] + dr
                            if 0 <= c < cols and 0 <= r < rows:
                                claimed[r, c] = True
                # Also mark cells around the drone's current position
                # (it will scan there when its current path completes)
                if drone and drone.path:
                    dest = drone.path[-1]
                    for dc in range(-SCAN_RADIUS_CELLS, SCAN_RADIUS_CELLS + 1):
                        for dr in range(-SCAN_RADIUS_CELLS, SCAN_RADIUS_CELLS + 1):
                            c, r = dest[0] + dc, dest[1] + dr
                            if 0 <= c < cols and 0 <= r < rows:
                                claimed[r, c] = True
            return claimed

    def get_survivor_counts(self) -> tuple[int, int]:
        """Return (found, total) survivor counts."""
        with self._lock:
            found = sum(
                1 for s in self._survivors.values() if s.status == SurvivorStatus.FOUND
            )
            return found, len(self._survivors)

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

            if not drone.path:
                events.extend(self._process_scan_queue(drone))

            if (
                drone.battery <= BATTERY_LOW_THRESHOLD
                and drone.id not in self._low_battery_fired
            ):
                self._low_battery_fired.add(drone.id)
                events.append(BatteryLowEvent(drone_id=drone.id, battery=drone.battery))

            return events

        # Idle drone with pending scan queue (e.g. assigned while already at
        # the first scan point — approach path was empty)
        if self._peek_scan_queue_entry(drone.id):
            events.extend(self._process_scan_queue(drone))
            return events

        # Idle at non-base position: apply slow battery drain
        if not at_base:
            drone.battery = max(0.0, drone.battery - BATTERY_IDLE_DRAIN_PER_TICK)

            # Check for low battery threshold (fires once)
            if (
                drone.battery <= BATTERY_LOW_THRESHOLD
                and drone.id not in self._low_battery_fired
            ):
                self._low_battery_fired.add(drone.id)
                events.append(BatteryLowEvent(drone_id=drone.id, battery=drone.battery))

        return events

    def _process_scan_queue(self, drone: Drone) -> list[WorldEvent]:
        """Auto-scan at current position and advance to next waypoint.

        Called when drone.path is empty and there may be scan queue entries.
        Also handles mop-up: if the queue empties but the zone still has
        uncovered cells, generates a new plan for the remainder.
        Must hold _lock.
        """
        from agent.pathfinder import straight_line_path

        events: list[WorldEvent] = []
        entry = self._peek_scan_queue_entry(drone.id)

        if not entry:
            # No scan queue — check if zone needs mop-up
            events.extend(self._maybe_mop_up(drone))
            if not self._peek_scan_queue_entry(drone.id):
                # Truly done
                _ = self._drone_zone.pop(drone.id, None)
                drone.status = DroneStatus.IDLE
                events.append(
                    DroneArrivedEvent(
                        drone_id=drone.id, col=drone.col, row=drone.row
                    )
                )
            return events

        # Auto-scan at current position
        scan_events, scan_result = self._do_thermal_scan(drone.id)
        events.extend(scan_events)

        zone_id = self._drone_zone.get(drone.id)
        cov = 0.0
        if zone_id and zone_id in scan_result["zone_coverages"]:
            cov = scan_result["zone_coverages"][zone_id]
        events.append(
            DroneScannedEvent(
                drone_id=drone.id,
                col=drone.col,
                row=drone.row,
                survivors_found=scan_result["survivors_found"],
                zone_id=zone_id,
                coverage_ratio=cov,
            )
        )

        # Pop completed entry, advance to next waypoint
        self._pop_scan_queue_locked(drone.id)
        nxt = self._peek_scan_queue_entry(drone.id)

        if not nxt:
            # Queue exhausted — check if zone needs mop-up
            events.extend(self._maybe_mop_up(drone))
            nxt = self._peek_scan_queue_entry(drone.id)

        if nxt:
            segment, _scan_point = nxt
            if segment:
                drone.path = list(segment)
            else:
                drone.path = straight_line_path(
                    drone.col, drone.row,
                    _scan_point[0], _scan_point[1],
                )
            drone.status = DroneStatus.MOVING
        else:
            # Truly done — clear assignment, go idle
            _ = self._drone_zone.pop(drone.id, None)
            drone.status = DroneStatus.IDLE
            events.append(
                DroneArrivedEvent(
                    drone_id=drone.id, col=drone.col, row=drone.row
                )
            )

        return events

    def _maybe_mop_up(self, drone: Drone) -> list[WorldEvent]:
        """If the drone's assigned zone still has uncovered cells, generate
        a new scan queue for the remainder.  Must hold _lock."""
        from agent.coverage import generate_coverage_plan
        from agent.pathfinder import straight_line_path

        events: list[WorldEvent] = []
        zone_id = self._drone_zone.get(drone.id)
        if not zone_id:
            return events

        zone = self.grid.get_zone(zone_id)
        if zone is None or zone.fully_covered:
            return events

        # Generate a plan for remaining uncovered cells
        plan = generate_coverage_plan(
            self.grid, zone_id, scan_radius=SCAN_RADIUS_CELLS
        )
        if plan.is_empty:
            return events

        # Build scan queue from plan
        queue: list[tuple[list[tuple[int, int]], tuple[int, int]]] = []
        for i, sp in enumerate(plan.scan_points):
            seg = plan.segments[i] if i < len(plan.segments) else []
            if i == 0:
                # Approach from drone's current position
                approach = straight_line_path(
                    drone.col, drone.row, sp[0], sp[1]
                )
                seg = approach + list(seg)
            queue.append((seg, sp))

        self._drone_scan_queue[drone.id] = queue
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

    def get_zones(self) -> dict[str, dict]:  # pyright: ignore[reportMissingTypeArgument]
        """Return all zones with their status and coverage."""
        with self._lock:
            return {zid: z.to_dict() for zid, z in self.grid.get_all_zones().items()}

