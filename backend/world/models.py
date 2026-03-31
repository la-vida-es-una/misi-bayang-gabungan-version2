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


# ── Zone status ──────────────────────────────────────────────────────────────


class ZoneStatus(str, Enum):
    IDLE = "idle"  # zone exists but is not being scanned
    SCANNING = "scanning"  # actively being scanned by drones
    COMPLETED = "completed"  # 100% coverage reached


# ── Mission phase ─────────────────────────────────────────────────────────────
# Simplified: no PAUSED — zone lifecycle is per-zone, not global.


class MissionPhase(str, Enum):
    PENDING = "pending"  # map defined, not yet started
    RUNNING = "running"  # world is ticking
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


# ── Zone lifecycle events ────────────────────────────────────────────────────


@dataclass
class ZoneAddedEvent:
    """A new search zone was registered on the grid."""

    type: Literal["zone_added"] = "zone_added"
    zone_id: str = ""
    label: str = ""
    zone_cells: int = 0


@dataclass
class ZoneRemovedEvent:
    """A zone was removed from the grid."""

    type: Literal["zone_removed"] = "zone_removed"
    zone_id: str = ""


@dataclass
class ScanStartedEvent:
    """One or more zones transitioned to scanning."""

    type: Literal["scan_started"] = "scan_started"
    zone_ids: list[str] = field(default_factory=list)


@dataclass
class ScanStoppedEvent:
    """One or more zones stopped scanning (back to idle)."""

    type: Literal["scan_stopped"] = "scan_stopped"
    zone_ids: list[str] = field(default_factory=list)


@dataclass
class ZoneCoveredEvent:
    """All cells in a specific zone have been scanned."""

    type: Literal["zone_covered"] = "zone_covered"
    zone_id: str = ""
    total_cells: int = 0


@dataclass
class MissionResumedEvent:
    type: Literal["mission_resumed"] = "mission_resumed"


@dataclass
class DroneScannedEvent:
    """Engine auto-scanned at a waypoint — no MCP round-trip needed."""

    type: Literal["drone_scanned"] = "drone_scanned"
    drone_id: str = ""
    col: int = 0
    row: int = 0
    survivors_found: list[str] = field(default_factory=list)
    zone_id: str | None = None
    coverage_ratio: float = 0.0


@dataclass
class MissionEndedEvent:
    type: Literal["mission_ended"] = "mission_ended"
    survivors_found: int = 0
    total_survivors: int = 0
    zones_completed: int = 0


# ── Agent visibility events (streamed via SSE) ──────────────────────────────


@dataclass
class AgentThinkingEvent:
    """LLM chain-of-thought reasoning text."""

    type: Literal["agent_thinking"] = "agent_thinking"
    tick: int = 0
    content: str = ""


@dataclass
class AgentToolCallEvent:
    """Agent invoked a tool."""

    type: Literal["agent_tool_call"] = "agent_tool_call"
    tick: int = 0
    tool: str = ""
    args: dict = field(default_factory=dict)  # pyright: ignore[reportMissingTypeArgument]
    call_id: str = ""


@dataclass
class AgentToolResultEvent:
    """Tool returned a result to the agent."""

    type: Literal["agent_tool_result"] = "agent_tool_result"
    tick: int = 0
    tool: str = ""
    result: dict = field(default_factory=dict)  # pyright: ignore[reportMissingTypeArgument]
    call_id: str = ""


@dataclass
class AgentStoppedEvent:
    """Agent loop was paused by user."""

    type: Literal["agent_stopped"] = "agent_stopped"


@dataclass
class AgentResumedEvent:
    """Agent loop was resumed."""

    type: Literal["agent_resumed"] = "agent_resumed"


@dataclass
class AgentUserMessageEvent:
    """User sent a message to the agent."""

    type: Literal["agent_user_message"] = "agent_user_message"
    content: str = ""


@dataclass
class AgentErrorEvent:
    """An error occurred in the agent (LLM failure, tick crash, etc.)."""

    type: Literal["agent_error"] = "agent_error"
    tick: int = 0
    error: str = ""
    detail: str = ""  # full traceback or extended info


WorldEvent = (
    DroneMovedEvent
    | DroneArrivedEvent
    | DroneScannedEvent
    | SurvivorFoundEvent
    | BatteryLowEvent
    | OutOfBoundsRejectedEvent
    | DroneChargingEvent
    | ZoneAddedEvent
    | ZoneRemovedEvent
    | ScanStartedEvent
    | ScanStoppedEvent
    | ZoneCoveredEvent
    | MissionResumedEvent
    | MissionEndedEvent
    | AgentThinkingEvent
    | AgentToolCallEvent
    | AgentToolResultEvent
    | AgentStoppedEvent
    | AgentResumedEvent
    | AgentUserMessageEvent
    | AgentErrorEvent
)
