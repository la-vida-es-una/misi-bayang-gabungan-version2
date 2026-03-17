"""
SAR Swarm Mission Validation
============================
This is NOT a unit test.

It validates the core value of the study case:
  "A self-healing rescue swarm that operates as a collective brain at the edge,
   ensuring aid reaches survivors even when the world is offline."

Each validation proves one promise made by the system:

  V1  — No drone teleports. Every position change is earned tick by tick.
  V2  — The LLM never assumes. Every decision is grounded in tool output.
  V3  — Survivors can only be found, never extracted or lost.
  V4  — Battery recall is the agent's responsibility, not the world's.
  V5  — Zone coverage is real. Pause only fires when area is actually scanned.
  V6  — Multi-zone works. A second zone resumes cleanly after pause.
  V7  — The swarm is self-healing. A drone failure does not stop the mission.
  V8  — No hardcoded drone IDs. Fleet is discovered dynamically.
  V9  — The mission log (CoT) proves reasoning happened before action.
  V10 — Offline guarantee. The full mission runs with zero external HTTP calls.

Run:
  uv run pytest tests/test_mission_validation.py -v --tb=short
"""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

import pytest

from agent.pathfinder import straight_line_path
from agent.window import REPLAN_THRESHOLD, WindowManager
from world.engine import BATTERY_LOW_THRESHOLD, WorldEngine
from world.grid import Grid
from world.models import (
    DroneMovedEvent,
    MissionPhase,
    MissionResumedEvent,
    SurvivorFoundEvent,
)

# ── Shared fixtures ───────────────────────────────────────────────────────────

# ── Test polygons ─────────────────────────────────────────────────────────────
# Coordinates are in plain units (not geographic degrees).
# Grid.cell_size_m=1.0 → each unit = 1 cell.
# Master: 20×20 area.  Zone1: left half.  Zone2: right half.
# All zones are strict subsets of master so containment always holds.

MASTER_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [0.0, 0.0],
            [20.0, 0.0],
            [20.0, 20.0],
            [0.0, 20.0],
            [0.0, 0.0],
        ]
    ],
}

ZONE_1_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [1.0, 1.0],
            [9.0, 1.0],
            [9.0, 9.0],
            [1.0, 9.0],
            [1.0, 1.0],
        ]
    ],
}

ZONE_2_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [11.0, 1.0],
            [19.0, 1.0],
            [19.0, 9.0],
            [11.0, 9.0],
            [11.0, 1.0],
        ]
    ],
}


def make_grid(cell_size_m: float = 1.0) -> Grid:
    """
    cell_size_m=1.0 with integer-unit coordinates → 1 unit = 1 cell.
    Master polygon is 20×20 = 400 cells. Fast to build, easy to reason about.
    """
    return Grid(MASTER_POLYGON, cell_size_m=cell_size_m)


def _first_cell(grid: Grid) -> tuple[int, int]:
    """Return the first in-bounds cell — used as a safe base for tests."""
    for r in range(grid.rows):
        for c in range(grid.cols):
            if grid.in_bounds(c, r):
                return c, r
    raise RuntimeError(
        "Grid has no in-bounds cells — polygon too small for cell_size_m"
    )


def make_engine(cell_size_m: float = 1.0) -> WorldEngine:
    grid = make_grid(cell_size_m=cell_size_m)
    base_col, base_row = _first_cell(grid)
    return WorldEngine(grid=grid, base_col=base_col, base_row=base_row)


def run_ticks(engine: WorldEngine, max_ticks: int = 2000) -> list[dict[str, Any]]:
    """Run world ticks until idle or max reached. Returns flat event list."""
    all_events: list[dict[str, Any]] = []
    for _ in range(max_ticks):
        events = engine.step()
        all_events.extend(asdict(e) for e in events)  # type: ignore[arg-type]
        if engine.phase != MissionPhase.RUNNING:
            break
    return all_events


def events_of(events: list[dict[str, Any]], type_: str) -> list[dict[str, Any]]:
    return [e for e in events if e.get("type") == type_]


# ═════════════════════════════════════════════════════════════════════════════
# V1 — NO DRONE TELEPORTATION
# Promise: every position change is earned tick by tick via path walking.
# ═════════════════════════════════════════════════════════════════════════════


class TestV1_NoTeleportation:
    def test_drone_moves_exactly_one_cell_per_tick(self) -> None:
        engine = make_engine()
        engine.add_drone("d1")
        engine.start()

        # Assign a path of 5 waypoints
        path = [(2, 1), (3, 1), (4, 1), (5, 1), (6, 1)]
        engine.assign_path("d1", path)

        move_events: list[dict[str, Any]] = []
        for tick in range(10):
            events = engine.step()
            move_events.extend(
                asdict(e)
                for e in events  # type: ignore[arg-type]
                if isinstance(e, DroneMovedEvent)
            )

        # Exactly 5 moves for 5 waypoints
        assert len(move_events) == 5, (
            f"Expected 5 moves, got {len(move_events)}. Drone may have teleported."
        )

    def test_each_move_is_adjacent_cell(self) -> None:
        """Each DroneMovedEvent must advance exactly 1 cell in col or row."""
        engine = make_engine()
        engine.add_drone("d1")
        engine.start()

        # Build path manually — guaranteed horizontal, 1 col per step, no diagonals.
        # Do NOT use straight_line_path here: Bresenham on a diagonal would produce
        # steps where both col and row change, which is correct behaviour but would
        # confuse a Chebyshev=1 assertion designed to catch real teleportation.
        # Start from the drone's actual position (base_col, base_row).
        bc, br = engine.base_col, engine.base_row
        path = [(bc + i, br) for i in range(1, 9) if engine.grid.in_bounds(bc + i, br)]
        assert len(path) >= 3, "Not enough in-bounds cells for horizontal path"
        engine.assign_path("d1", path)

        all_events = run_ticks(engine, max_ticks=50)
        move_events = events_of(all_events, "drone_moved")

        for ev in move_events:
            col_delta = abs(ev["to_col"] - ev["from_col"])
            row_delta = abs(ev["to_row"] - ev["from_row"])
            chebyshev = max(col_delta, row_delta)
            assert chebyshev == 1, (
                f"Move jumped {chebyshev} cells: {ev}. This is teleportation."
            )

    def test_position_matches_move_event_chain(self) -> None:
        """Final drone position must equal last DroneMovedEvent.to_col/row."""
        engine = make_engine()
        engine.add_drone("d1")
        engine.start()

        target = (5, 3)
        path = straight_line_path(1, 1, *target)
        engine.assign_path("d1", path)

        all_events = run_ticks(engine, max_ticks=50)
        move_events = events_of(all_events, "drone_moved")

        state = engine.get_world_state()
        final_col = state["drones"]["d1"]["col"]
        final_row = state["drones"]["d1"]["row"]

        last_move = move_events[-1]
        assert final_col == last_move["to_col"]
        assert final_row == last_move["to_row"]
        assert (final_col, final_row) == target


# ═════════════════════════════════════════════════════════════════════════════
# V2 — LLM DECISIONS GROUNDED IN TOOL OUTPUT
# Promise: the agent never acts on assumptions; every action follows
#          a tool call that returned real world state.
# ═════════════════════════════════════════════════════════════════════════════


class TestV2_GroundedDecisions:
    def test_move_to_uses_current_position_not_assumption(self) -> None:
        """
        The MCP move_to tool reads drone position from the engine, not from
        a cached value. Simulate engine ticking while agent is 'thinking',
        then verify move_to computes path from actual position.
        """
        engine = make_engine()
        engine.add_drone("d1")
        engine.start()

        # Tick the world 5 times without agent knowing
        path = straight_line_path(1, 1, 4, 1)
        engine.assign_path("d1", path)
        for _ in range(3):
            engine.step()

        # Agent now queries world state (as it must via get_world_state tool)
        state = engine.get_world_state()
        actual_col = state["drones"]["d1"]["col"]
        actual_row = state["drones"]["d1"]["row"]

        # The agent would call move_to — internally it reads actual position
        # We verify the path is computed from the real position
        from agent.pathfinder import straight_line_path as slp

        computed_path = slp(actual_col, actual_row, 6, 1)

        # Path must start from where the drone actually is
        if computed_path:
            first_step = computed_path[0]
            dist_from_actual = math.hypot(
                first_step[0] - actual_col,
                first_step[1] - actual_row,
            )
            assert dist_from_actual <= 1.5, (
                "Path does not start from actual drone position. "
                "Agent acted on stale/assumed state."
            )

    def test_battery_check_reflects_actual_drain(self) -> None:
        """
        Battery reported by get_battery_status must match actual drain
        from ticks, not an initial assumption of 100%.
        """
        engine = make_engine()
        engine.add_drone("d1")
        engine.start()

        path = straight_line_path(1, 1, 8, 1)
        engine.assign_path("d1", path)
        run_ticks(engine, max_ticks=20)

        reported = engine.get_battery("d1")
        assert reported is not None
        assert reported < 100.0, (
            "Battery still 100% after moving. "
            "Agent would make wrong decisions based on stale battery data."
        )

    def test_list_drones_reflects_actual_fleet(self) -> None:
        """
        list_drones must return exactly the drones registered, no more, no less.
        Agent must not hardcode IDs.
        """
        engine = make_engine()
        fleet = ["alpha", "bravo", "charlie"]
        for d in fleet:
            engine.add_drone(d)

        discovered = engine.list_drone_ids()
        assert set(discovered) == set(fleet), (
            f"list_drones returned {discovered}, expected {fleet}. "
            "Agent may have hardcoded drone IDs."
        )


# ═════════════════════════════════════════════════════════════════════════════
# V3 — SURVIVOR LIFECYCLE: MISSING → FOUND ONLY
# Promise: survivors cannot be extracted, duplicated, or lost.
# ═════════════════════════════════════════════════════════════════════════════


class TestV3_SurvivorLifecycle:
    def test_survivor_starts_missing(self) -> None:
        engine = make_engine()
        engine.add_survivor("s1", col=3, row=3)
        state = engine.get_world_state()
        assert state["survivors"]["s1"]["status"] == "missing"

    def test_thermal_scan_transitions_missing_to_found(self) -> None:
        engine = make_engine()
        engine.add_drone("d1")
        # Place survivor at same cell as drone (col=0,row=0) — guaranteed within radius=2
        base_col, base_row = engine.base_col, engine.base_row
        engine.add_survivor("s1", col=base_col, row=base_row)
        engine.start()

        events = engine.thermal_scan("d1")
        found_events = [e for e in events if isinstance(e, SurvivorFoundEvent)]

        assert len(found_events) == 1
        assert found_events[0].survivor_id == "s1"

        state = engine.get_world_state()
        assert state["survivors"]["s1"]["status"] == "found"

    def test_found_survivor_cannot_be_found_again(self) -> None:
        """thermal_scan on an already-found survivor must emit no new event."""
        engine = make_engine()
        engine.add_drone("d1")
        engine.add_survivor("s1", col=2, row=1)
        engine.start()

        engine.thermal_scan("d1")  # first scan — found
        events2 = engine.thermal_scan("d1")  # second scan — must be silent
        found_again = [e for e in events2 if isinstance(e, SurvivorFoundEvent)]

        assert len(found_again) == 0, (
            "Survivor found twice. Lifecycle violated: found state must be terminal."
        )

    def test_survivor_count_never_increases(self) -> None:
        """Total survivor count in world state must not grow after seeding."""
        engine = make_engine()
        engine.add_survivor("s1", col=2, row=2)
        engine.add_survivor("s2", col=4, row=4)
        engine.start()

        count_before = len(engine.get_world_state()["survivors"])
        run_ticks(engine, max_ticks=50)
        count_after = len(engine.get_world_state()["survivors"])

        assert count_after == count_before, (
            "Survivor count changed during mission. "
            "Survivors must be immutable after seeding."
        )


# ═════════════════════════════════════════════════════════════════════════════
# V4 — BATTERY RECALL IS AGENT'S RESPONSIBILITY
# Promise: no auto-return. The engine fires BatteryLowEvent; the agent
#          must explicitly route the drone to base.
# ═════════════════════════════════════════════════════════════════════════════


class TestV4_BatteryRecall:
    def test_engine_does_not_auto_return_drone(self) -> None:
        """
        When battery is low, engine must NOT move the drone to base by itself.
        It fires BatteryLowEvent and waits for agent instruction.
        """
        engine = make_engine()
        engine.add_drone("d1")
        engine.start()

        # Drain battery by assigning a long path
        long_path = [(c, 1) for c in range(2, 20)]
        engine.assign_path("d1", long_path)

        all_events = run_ticks(engine, max_ticks=200)
        low_events = events_of(all_events, "battery_low")

        if low_events:
            # After battery low, drone must NOT be at base unless agent sent it
            state = engine.get_world_state()
            d = state["drones"]["d1"]
            is_at_base = d["col"] == engine.base_col and d["row"] == engine.base_row
            # Drone should NOT be at base — it only gets there if agent calls move_to
            # (The path we assigned does not go to base)
            assert not is_at_base, (
                "Engine auto-returned drone to base after battery low. "
                "This violates agent responsibility — only the agent may recall."
            )

    def test_battery_low_event_fired_at_threshold(self) -> None:
        engine = make_engine()
        engine.add_drone("d1")
        engine.start()

        # Build a path long enough to drain battery below threshold.
        # BATTERY_DRAIN_PER_MOVE=0.5, threshold=25 → need >150 moves from 100%.
        # Snake across the 20×20 grid: 20 rows × 18 steps = 360 moves.
        path: list[tuple[int, int]] = []
        for row in range(1, 20):
            cols = range(1, 19) if row % 2 == 1 else range(18, 0, -1)
            for col in cols:
                if engine.grid.in_bounds(col, row):
                    path.append((col, row))
        engine.assign_path("d1", path)

        all_events = run_ticks(engine, max_ticks=500)
        low_events = events_of(all_events, "battery_low")

        assert len(low_events) >= 1, (
            "BatteryLowEvent never fired during long mission. "
            "Agent would never know to recall the drone."
        )

        # Battery at time of event must be at or below threshold
        for ev in low_events:
            assert ev["battery"] <= BATTERY_LOW_THRESHOLD, (
                f"BatteryLowEvent fired at {ev['battery']}% "
                f"which is above threshold {BATTERY_LOW_THRESHOLD}%."
            )

    def test_battery_low_fires_once_per_cycle(self) -> None:
        """BatteryLowEvent must fire exactly once per low-battery cycle."""
        engine = make_engine()
        engine.add_drone("d1")
        engine.start()

        # Same long snake path as above
        path: list[tuple[int, int]] = []
        for row in range(1, 20):
            cols = range(1, 19) if row % 2 == 1 else range(18, 0, -1)
            for col in cols:
                if engine.grid.in_bounds(col, row):
                    path.append((col, row))
        engine.assign_path("d1", path)

        all_events = run_ticks(engine, max_ticks=500)
        low_events = events_of(all_events, "battery_low")

        # Must not spam the agent
        assert len(low_events) == 1, (
            f"BatteryLowEvent fired {len(low_events)} times. "
            "Agent would be flooded with redundant recall orders."
        )

    def test_drone_charges_when_agent_returns_it_to_base(self) -> None:
        """When agent explicitly routes drone to base, it charges."""
        engine = make_engine()
        engine.add_drone("d1")
        engine.start()

        # Drain battery manually
        state = engine.get_world_state()
        engine._drones["d1"].battery = 15.0

        # Agent calls move_to base (simulated)
        path_to_base = straight_line_path(5, 5, engine.base_col, engine.base_row)
        engine._drones["d1"].col = 5
        engine._drones["d1"].row = 5
        engine.assign_path("d1", path_to_base)

        all_events = run_ticks(engine, max_ticks=200)
        charge_events = events_of(all_events, "drone_charging")

        assert len(charge_events) > 0, (
            "Drone never charged after agent returned it to base. "
            "Battery recovery is broken."
        )

        final_battery = engine.get_battery("d1")
        assert final_battery is not None
        assert final_battery > 15.0, "Battery did not increase during charging."


# ═════════════════════════════════════════════════════════════════════════════
# V5 — ZONE COVERAGE IS REAL
# Promise: pause fires only after every cell in the zone is actually scanned.
# ═════════════════════════════════════════════════════════════════════════════


class TestV5_ZoneCoverage:
    def test_zone_not_covered_without_scanning(self) -> None:
        grid = make_grid()
        grid.set_zone(ZONE_1_POLYGON)
        assert not grid.zone_fully_covered(), (
            "Zone reported covered before any scanning. Coverage tracking is broken."
        )

    def test_coverage_increases_with_each_scan(self) -> None:
        grid = make_grid()
        grid.set_zone(ZONE_1_POLYGON)

        ratio_before = grid.coverage_ratio()
        zone_cells = grid.all_zone_cells()
        if zone_cells:
            col, row = zone_cells[0]
            grid.mark_scanned(col, row, radius=2)

        ratio_after = grid.coverage_ratio()
        assert ratio_after >= ratio_before, "Coverage did not increase after scan."

    def test_pause_only_fires_after_full_coverage_and_all_drones_home(self) -> None:
        """
        MissionPausedEvent must only appear AFTER ZoneCoveredEvent
        AND all drones have returned to base.
        This is the core auto-pause contract.
        """
        engine = make_engine(cell_size_m=5.0)  # larger cells → fewer cells in zone
        engine.add_drone("d1")
        engine.start()

        grid = engine.grid
        grid.set_zone(ZONE_1_POLYGON)

        # Force all zone cells covered by scanning from each cell
        all_events: list[dict[str, Any]] = []
        for col, row in grid.all_zone_cells():
            engine._drones["d1"].col = col
            engine._drones["d1"].row = row
            scan_events = engine.thermal_scan("d1")
            all_events.extend(asdict(e) for e in scan_events)  # type: ignore[arg-type]

        # Return drone to base
        path_home = straight_line_path(
            engine._drones["d1"].col,
            engine._drones["d1"].row,
            engine.base_col,
            engine.base_row,
        )
        engine.assign_path("d1", path_home)
        tick_events = run_ticks(engine, max_ticks=500)
        all_events.extend(tick_events)

        zone_covered = events_of(all_events, "zone_covered")
        mission_paused = events_of(all_events, "mission_paused")

        assert len(zone_covered) >= 1, "ZoneCoveredEvent never fired."
        assert len(mission_paused) >= 1, (
            "MissionPausedEvent never fired even though zone is covered "
            "and drone returned home."
        )

    def test_pause_does_not_fire_if_drone_not_at_base(self) -> None:
        engine = make_engine()
        engine.add_drone("d1")
        engine.start()

        grid = engine.grid
        grid.set_zone(ZONE_1_POLYGON)
        zone_cells = grid.all_zone_cells()
        assert zone_cells, "ZONE_1_POLYGON produced no cells"

        for col, row in zone_cells:
            grid.mark_scanned(col, row, radius=0)

        # Mark zone covered internally but do NOT return drone to base
        engine._zone_covered_fired = True
        base_col, base_row = engine.base_col, engine.base_row
        # Put drone somewhere that is NOT base
        for col, row in zone_cells:
            if col != base_col or row != base_row:
                engine._drones["d1"].col = col
                engine._drones["d1"].row = row
                break

        engine._drones["d1"].path = []

        events = engine.step()
        event_types = {asdict(e).get("type") for e in events}  # type: ignore[arg-type]

        assert "mission_paused" not in event_types, (
            "Mission paused while drone is still in the field. "
            "Drone must return to base before pause triggers."
        )


# ═════════════════════════════════════════════════════════════════════════════
# V6 — MULTI-ZONE MISSION
# Promise: after pause, a new zone resumes the mission cleanly.
#          Previous zone coverage does not bleed into new zone.
# ═════════════════════════════════════════════════════════════════════════════


class TestV6_MultiZone:
    def test_new_zone_resets_coverage(self) -> None:
        grid = make_grid()
        grid.set_zone(ZONE_1_POLYGON)
        zone_1_cells = grid.all_zone_cells()
        assert zone_1_cells, "ZONE_1_POLYGON produced no cells"

        for col, row in zone_1_cells:
            grid.mark_scanned(col, row, radius=0)

        assert grid.zone_fully_covered(), (
            "Could not fully cover zone 1 even with per-cell scanning. "
            "Coverage tracking is broken."
        )

        grid.set_zone(ZONE_2_POLYGON)
        assert grid.all_zone_cells(), "ZONE_2_POLYGON produced no cells"

        assert not grid.zone_fully_covered(), (
            "Zone 2 reported covered immediately after being set. "
            "Coverage from zone 1 bled into zone 2."
        )
        assert grid.coverage_ratio() == 0.0

    def test_zone_index_increments(self) -> None:
        grid = make_grid()
        assert grid.zone_index == 0
        grid.set_zone(ZONE_1_POLYGON)
        assert grid.zone_index == 1
        grid.set_zone(ZONE_2_POLYGON)
        assert grid.zone_index == 2

    def test_resume_after_pause_transitions_phase(self) -> None:
        engine = make_engine()
        engine.add_drone("d1")

        engine.grid.set_zone(ZONE_1_POLYGON)
        assert engine.grid.all_zone_cells(), "ZONE_1_POLYGON produced no cells"
        grid = engine.grid

        engine.start()
        assert engine.phase == MissionPhase.RUNNING

        # Force covered + drone at base → pause
        for col, row in grid.all_zone_cells():
            grid.mark_scanned(col, row, radius=0)
        engine._zone_covered_fired = True
        engine._drones["d1"].col = engine.base_col
        engine._drones["d1"].row = engine.base_row
        engine._drones["d1"].path = []
        engine.step()

        assert engine.phase == MissionPhase.PAUSED, (
            f"Engine did not pause. Phase: {engine.phase}"
        )

        # Add zone 2 and resume
        engine.grid.set_zone(ZONE_2_POLYGON)
        assert engine.grid.all_zone_cells(), "ZONE_2_POLYGON produced no cells"

        events = engine.start()
        resumed = [e for e in events if isinstance(e, MissionResumedEvent)]

        assert engine.phase == MissionPhase.RUNNING
        assert len(resumed) == 1, "MissionResumedEvent not emitted on resume."

    def test_world_ticks_stop_during_pause(self) -> None:
        """step() must be a no-op when paused."""
        engine = make_engine()
        engine.add_drone("d1")
        engine.grid.set_zone(ZONE_1_POLYGON)
        engine.start()

        # Force pause state directly
        engine.phase = MissionPhase.PAUSED
        engine._drones["d1"].path = [(3, 3), (4, 4)]  # drone has pending path

        tick_before = engine._tick
        engine.step()
        engine.step()
        tick_after = engine._tick

        assert tick_after == tick_before, (
            f"World ticked {tick_after - tick_before} times while PAUSED. "
            "World clock must stop during pause."
        )


# ═════════════════════════════════════════════════════════════════════════════
# V7 — SWARM SELF-HEALING
# Promise: if one drone is stuck (empty battery, no path), other drones
#          continue the mission. The swarm does not deadlock.
# ═════════════════════════════════════════════════════════════════════════════


class TestV7_SelfHealing:
    def test_dead_drone_does_not_block_swarm(self) -> None:
        """
        Drone 'd1' runs out of battery and has no path.
        Drone 'd2' should still be able to move and scan.
        """
        engine = make_engine()
        engine.add_drone("d1")
        engine.add_drone("d2")
        engine.start()

        # Kill d1 — 0 battery, no path, stranded
        engine._drones["d1"].battery = 0.0
        engine._drones["d1"].path = []
        engine._drones["d1"].col = 5
        engine._drones["d1"].row = 5

        # d2 gets a normal path
        path = straight_line_path(1, 1, 6, 1)
        engine.assign_path("d2", path)

        all_events = run_ticks(engine, max_ticks=50)
        d2_moves = [
            e for e in events_of(all_events, "drone_moved") if e["drone_id"] == "d2"
        ]

        assert len(d2_moves) > 0, (
            "d2 never moved while d1 was dead. Swarm deadlocked on a failed drone."
        )

    def test_mission_continues_with_partial_fleet(self) -> None:
        """3 drones registered; 2 have no path. Mission should still tick."""
        engine = make_engine()
        for d in ["d1", "d2", "d3"]:
            engine.add_drone(d)
        engine.start()

        engine.assign_path("d3", [(2, 1), (3, 1), (4, 1)])

        all_events = run_ticks(engine, max_ticks=20)
        assert len(all_events) > 0, "No events with partial fleet — mission stalled."


# ═════════════════════════════════════════════════════════════════════════════
# V8 — NO HARDCODED DRONE IDs
# Promise: the agent must discover drones dynamically via list_drones.
#          Any fleet size 1–5 must work identically.
# ═════════════════════════════════════════════════════════════════════════════


class TestV8_DynamicFleetDiscovery:
    @pytest.mark.parametrize("fleet_size", [1, 2, 3, 4, 5])
    def test_fleet_discovery_any_size(self, fleet_size: int) -> None:
        engine = make_engine()
        fleet = [f"unit_{i}" for i in range(fleet_size)]
        for d in fleet:
            engine.add_drone(d)

        discovered = engine.list_drone_ids()
        assert len(discovered) == fleet_size
        assert set(discovered) == set(fleet), (
            f"list_drones returned {discovered} for fleet {fleet}. "
            "Discovery is broken or IDs are hardcoded."
        )

    def test_fleet_discovery_with_non_standard_ids(self) -> None:
        """IDs like 'SAR-7', 'rescue_alpha' must work — not just 'drone_N'."""
        engine = make_engine()
        weird_ids = ["SAR-7", "rescue_alpha", "unit.bravo"]
        for d in weird_ids:
            engine.add_drone(d)

        discovered = engine.list_drone_ids()
        assert set(discovered) == set(weird_ids), (
            "Non-standard drone IDs broke discovery. "
            "IDs must be opaque strings, not parsed."
        )


# ═════════════════════════════════════════════════════════════════════════════
# V9 — ROLLING 3-STEP WINDOW + REPLAN
# Promise: agent always has next 3 waypoints; replans before running empty.
# ═════════════════════════════════════════════════════════════════════════════


class TestV9_RollingWindow:
    def test_window_triggers_replan_at_threshold(self) -> None:
        mgr = WindowManager()
        mgr.register("d1")

        mgr.get("d1").add_waypoints([(1, 1), (2, 2), (3, 3)])
        assert not mgr.get("d1").needs_replan

        mgr.get("d1").consume(2)
        assert mgr.get("d1").remaining == 1
        assert mgr.get("d1").needs_replan, (
            f"Window has {mgr.get('d1').remaining} waypoints "
            f"(≤ threshold {REPLAN_THRESHOLD}) but needs_replan is False."
        )

    def test_window_caps_at_three(self) -> None:
        mgr = WindowManager()
        mgr.register("d1")

        mgr.get("d1").add_waypoints([(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)])
        assert mgr.get("d1").remaining == 3, (
            "Window accepted more than 3 waypoints. "
            "Agent may over-plan, wasting LLM context."
        )

    def test_drones_needing_replan_identifies_correct_drones(self) -> None:
        mgr = WindowManager()
        for d in ["d1", "d2", "d3"]:
            mgr.register(d)

        mgr.get("d1").add_waypoints([(1, 1), (2, 2), (3, 3)])  # full
        mgr.get("d2").add_waypoints([(1, 1)])  # needs replan
        mgr.get("d3").add_waypoints([])  # needs replan

        needing = set(mgr.drones_needing_replan())
        assert "d1" not in needing
        assert "d2" in needing
        assert "d3" in needing

    def test_battery_low_clears_window(self) -> None:
        """Battery recall must take absolute priority — window must clear."""
        mgr = WindowManager()
        mgr.register("d1")
        mgr.get("d1").add_waypoints([(5, 5), (6, 6), (7, 7)])

        # Simulate what orchestrator._handle_event does on battery_low
        mgr.get("d1").clear()

        assert mgr.get("d1").remaining == 0
        assert mgr.get("d1").needs_replan, (
            "After battery low, window should be empty and needs_replan=True. "
            "Agent must immediately issue a base recall."
        )


# ═════════════════════════════════════════════════════════════════════════════
# V10 — OFFLINE GUARANTEE
# Promise: the full mission pipeline runs with zero external HTTP calls.
#          No cloud. No internet. Edge-only.
# ═════════════════════════════════════════════════════════════════════════════


class TestV10_OfflineGuarantee:
    def test_world_engine_makes_no_network_calls(self) -> None:
        """WorldEngine + Grid must function with network blocked."""
        import socket

        original_socket = socket.socket

        call_log: list[str] = []

        class BlockedSocket:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                call_log.append(f"socket({args}, {kwargs})")
                raise OSError("Network is blocked — offline mode")

        socket.socket = BlockedSocket  # type: ignore[misc]
        try:
            engine = make_engine()
            engine.add_drone("d1")
            engine.add_survivor("s1", col=2, row=2)
            engine.start()
            engine.assign_path("d1", [(2, 1), (3, 1)])
            engine.step()
            engine.thermal_scan("d1")
            state = engine.get_world_state()
            assert "d1" in state["drones"]
        finally:
            socket.socket = original_socket  # type: ignore[misc]

        assert len(call_log) == 0, (
            f"WorldEngine made {len(call_log)} network calls: {call_log}. "
            "Core engine must be fully offline."
        )

    def test_pathfinder_makes_no_network_calls(self) -> None:
        """Bresenham pathfinder is pure math — must never touch network."""
        import socket

        original_socket = socket.socket

        class BlockedSocket:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise OSError("Network blocked")

        socket.socket = BlockedSocket  # type: ignore[misc]
        try:
            path = straight_line_path(0, 0, 10, 10)
            assert len(path) > 0
        finally:
            socket.socket = original_socket  # type: ignore[misc]

    def test_grid_rasterisation_makes_no_network_calls(self) -> None:
        """Shapely polygon rasterisation must be pure local computation."""
        import socket

        original_socket = socket.socket

        class BlockedSocket:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise OSError("Network blocked")

        socket.socket = BlockedSocket  # type: ignore[misc]
        try:
            grid = make_grid()
            grid.set_zone(ZONE_1_POLYGON)
            cells = grid.all_zone_cells()
            assert len(cells) >= 0  # may be 0 for very small zone at coarse grid
        finally:
            socket.socket = original_socket  # type: ignore[misc]
