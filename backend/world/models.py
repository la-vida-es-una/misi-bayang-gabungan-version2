"""
Pure dataclasses — no behaviour, no imports from other world modules.
These are the only structs that cross layer boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


# ── Survivor ────────────────────────────────────────────────────────────────


class SurvivorStatus(str, Enum):
    MISSING = "missing"
    FOUND = "found"


@dataclass
class Survivor:
    id: str
    col: int
    row: int
    status: SurvivorStatus = SurvivorStatus.MISSING


# ── Drone ────────────────────────────────────────────────────────────────────


class DroneStatus(str, Enum):
    IDLE = "idle"
    MOVING = "moving"
    SCANNING = "scanning"
    CHARGING = "charging"


@dataclass
class Drone:
    id: str
    col: int
    row: int
    battery: float = 100.0
    status: DroneStatus = DroneStatus.IDLE
    path: list[tuple[int, int]] = field(default_factory=list)


# ── Mission phase ─────────────────────────────────────────────────────────────


class MissionPhase(str, Enum):
    PENDING = "pending"  # map defined, not yet started
    RUNNING = "running"
    PAUSED = "paused"  # zone covered + all drones at base
    ENDED = "ended"


# ── Events (returned by engine.step()) ───────────────────────────────────────


@dataclass
class DroneMovedEvent:
    type: Literal["drone_moved"] = "drone_moved"
    drone_id: str = ""
    from_col: int = 0
    from_row: int = 0
    to_col: int = 0
    to_row: int = 0


@dataclass
class DroneArrivedEvent:
    type: Literal["drone_arrived"] = "drone_arrived"
    drone_id: str = ""
    col: int = 0
    row: int = 0


@dataclass
class SurvivorFoundEvent:
    type: Literal["survivor_found"] = "survivor_found"
    drone_id: str = ""
    survivor_id: str = ""
    col: int = 0
    row: int = 0


@dataclass
class BatteryLowEvent:
    type: Literal["battery_low"] = "battery_low"
    drone_id: str = ""
    battery: float = 0.0


@dataclass
class OutOfBoundsRejectedEvent:
    type: Literal["out_of_bounds_rejected"] = "out_of_bounds_rejected"
    drone_id: str = ""
    col: int = 0
    row: int = 0


@dataclass
class DroneChargingEvent:
    type: Literal["drone_charging"] = "drone_charging"
    drone_id: str = ""
    battery: float = 0.0


@dataclass
class ZoneCoveredEvent:
    """All cells in current zone have been scanned."""

    type: Literal["zone_covered"] = "zone_covered"
    zone_index: int = 0
    total_cells: int = 0


@dataclass
class MissionPausedEvent:
    """Zone covered AND all drones returned to base."""

    type: Literal["mission_paused"] = "mission_paused"
    zone_index: int = 0


@dataclass
class MissionResumedEvent:
    type: Literal["mission_resumed"] = "mission_resumed"
    zone_index: int = 0


@dataclass
class MissionEndedEvent:
    type: Literal["mission_ended"] = "mission_ended"
    survivors_found: int = 0
    total_survivors: int = 0
    zones_completed: int = 0


WorldEvent = (
    DroneMovedEvent
    | DroneArrivedEvent
    | SurvivorFoundEvent
    | BatteryLowEvent
    | OutOfBoundsRejectedEvent
    | DroneChargingEvent
    | ZoneCoveredEvent
    | MissionPausedEvent
    | MissionResumedEvent
    | MissionEndedEvent
)
