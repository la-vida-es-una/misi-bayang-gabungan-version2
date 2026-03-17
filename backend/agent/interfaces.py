"""
Interface contracts for all external dependencies.

This module defines Protocol classes (structural subtyping) that external
dependencies must satisfy.  The MCP team, simulation team, or any future
integrator just needs to implement these interfaces.  The agent **never**
cares about the concrete class.

All Protocols are @runtime_checkable so isinstance() works for assertions.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


# ═══════════════════════════════════════════════════════════════════════
#  Typed dictionaries — structured data flowing through the system
# ═══════════════════════════════════════════════════════════════════════


class DroneStatus(TypedDict):
    """Full status snapshot of a single drone."""

    drone_id: str
    battery: int
    x: int
    y: int
    state: str  # "explore" | "return"


class ScanResult(TypedDict):
    """Result of a thermal scan at a drone's current position."""

    survivor_detected: bool
    confidence: float
    x: int
    y: int


class MoveResult(TypedDict):
    """Result of a move_to command."""

    success: bool
    drone_id: str
    x: int
    y: int


class GridMap(TypedDict):
    """Current known state of the full grid."""

    scanned: list[list[int]]  # [[x, y], ...]
    survivors: list[list[int]]  # [[x, y], ...]


# ═══════════════════════════════════════════════════════════════════════
#  MCP Client Protocol
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class MCPClientProtocol(Protocol):
    """
    Any object implementing these async methods can be used as the MCP client.

    The real MCP client or any test double are valid as long as they satisfy
    this interface.  The agent **never** imports from ``mcp_server`` directly.
    """

    async def list_active_drones(self) -> dict[str, list[str]]:
        """Return ``{"drones": ["drone_0", "drone_1", ...]}``."""
        ...

    async def get_battery_status(self, drone_id: str) -> DroneStatus:
        """Return full status of a single drone including battery level."""
        ...

    async def move_to(self, drone_id: str, x: int, y: int) -> MoveResult:
        """Set a waypoint for the drone.  Returns success + target position."""
        ...

    async def step_world(self, ticks: int = 1) -> dict[str, Any]:
        """Advance the simulation by ``ticks`` steps.  Returns ``{"success", "new_tick"}``."""
        ...

    async def thermal_scan(self, drone_id: str) -> ScanResult:
        """Run thermal scan at the drone's current position."""
        ...

    async def return_to_base(self, drone_id: str) -> dict[str, Any]:
        """Recall drone to charging base."""
        ...

    async def get_grid_map(self) -> GridMap:
        """Get current known state of the full grid."""
        ...

    async def broadcast_alert(self, x: int, y: int, message: str) -> dict[str, Any]:
        """Broadcast survivor alert to all units."""
        ...


# ═══════════════════════════════════════════════════════════════════════
#  Agent Observer Protocol  (optional UI / frontend bridge)
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class AgentObserverProtocol(Protocol):
    """
    Optional observer for streaming agent updates to a frontend or API.

    If not provided, agent runs silently except for terminal logs.
    The API team can implement this to push updates to their endpoints.
    """

    def on_step_start(self, step: int, context: dict[str, Any]) -> None:
        """Called at the beginning of each reasoning step."""
        ...

    def on_reasoning(self, step: int, text: str) -> None:
        """Called when the LLM produces reasoning text."""
        ...

    def on_tool_call(self, tool_name: str, params: dict[str, Any], result: dict[str, Any]) -> None:
        """Called after a tool invocation completes."""
        ...

    def on_survivor_found(self, x: int, y: int, confidence: float) -> None:
        """Called when a survivor is detected during a thermal scan."""
        ...

    def on_mission_complete(self, summary: dict[str, Any]) -> None:
        """Called when the mission finishes (success or timeout)."""
        ...


# ═══════════════════════════════════════════════════════════════════════
#  Null Observer  (default — silent no-op implementation)
# ═══════════════════════════════════════════════════════════════════════


class NullObserver:
    """
    Default observer that does nothing.

    Used when no frontend / API observer is injected — the agent simply
    runs without pushing updates anywhere.
    """

    def on_step_start(self, step: int, context: dict[str, Any]) -> None:
        """No-op."""

    def on_reasoning(self, step: int, text: str) -> None:
        """No-op."""

    def on_tool_call(self, tool_name: str, params: dict[str, Any], result: dict[str, Any]) -> None:
        """No-op."""

    def on_survivor_found(self, x: int, y: int, confidence: float) -> None:
        """No-op."""

    def on_mission_complete(self, summary: dict[str, Any]) -> None:
        """No-op."""
