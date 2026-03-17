"""
LiveMCPClient — bridges MCPClientProtocol to a live SARWorld instance.

Translates string drone IDs ("drone_0") to Mesa integer IDs (0) for
direct SARWorld method calls. Movement is waypoint-based — drones navigate
at configured speed over simulation ticks instead of teleporting.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .interfaces import DroneStatus, GridMap, MoveResult, ScanResult

if TYPE_CHECKING:
    from simulation.world import SARWorld

logger = logging.getLogger(__name__)

BATTERY_DRAIN_SCAN = 1


class LiveMCPClient:
    """
    Implements MCPClientProtocol by wrapping a live SARWorld instance.

    All MCP method calls translate directly to SARWorld operations.
    """

    def __init__(self, world: "SARWorld") -> None:
        self._world = world

    # ── ID translation ───────────────────────────────────────────────

    @staticmethod
    def _to_int(drone_id: str) -> int:
        """'drone_0' -> 0.  Also accepts bare integers ('0')."""
        if "_" in drone_id:
            parts = drone_id.split("_")
            if len(parts) >= 2 and parts[1]:
                return int(parts[1])
        try:
            return int(drone_id)
        except ValueError:
            raise ValueError(
                f"Cannot parse drone_id {drone_id!r}: expected 'drone_<int>' or '<int>'"
            )

    # ── MCPClientProtocol implementation ─────────────────────────────

    async def list_active_drones(self) -> dict[str, list[str]]:
        active = self._world.list_active_drones()
        return {"drones": [f"drone_{d['id']}" for d in active]}

    async def get_battery_status(self, drone_id: str) -> DroneStatus:
        did = self._to_int(drone_id)
        drone = self._world.get_drone(did)
        if drone is None:
            raise ValueError(f"Drone {drone_id} not found")
        x, y = drone._pos()
        return DroneStatus(
            drone_id=drone_id,
            battery=int(drone.battery),
            x=x,
            y=y,
            state=drone.state.value,
        )

    async def move_to(self, drone_id: str, x: int, y: int) -> MoveResult:
        did = self._to_int(drone_id)
        drone = self._world.get_drone(did)
        if drone is None:
            return MoveResult(success=False, drone_id=drone_id, x=x, y=y)

        if drone.battery <= 0:
            return MoveResult(
                success=False, drone_id=drone_id, x=drone._pos()[0], y=drone._pos()[1]
            )

        result = self._world.set_drone_waypoint(did, x, y)
        if "error" in result:
            return MoveResult(success=False, drone_id=drone_id, x=x, y=y)

        return MoveResult(success=True, drone_id=drone_id, x=x, y=y)

    async def step_world(self, ticks: int = 1) -> dict:
        for _ in range(max(1, ticks)):
            self._world.step()
        return {"success": True, "new_tick": self._world.steps}

    async def thermal_scan(self, drone_id: str) -> ScanResult:
        did = self._to_int(drone_id)
        drone = self._world.get_drone(did)
        if drone is None:
            return ScanResult(survivor_detected=False, confidence=0.0, x=0, y=0)

        drone.battery = max(0.0, drone.battery - BATTERY_DRAIN_SCAN)

        dx, dy = drone._pos()
        result = self._world.thermal_scan(did)

        if "error" in result:
            return ScanResult(survivor_detected=False, confidence=0.0, x=dx, y=dy)

        detections = result.get("detections", [])
        if detections:
            det = detections[0]
            sx, sy = det["x"], det["y"]
            return ScanResult(survivor_detected=True, confidence=0.95, x=sx, y=sy)

        return ScanResult(survivor_detected=False, confidence=0.0, x=dx, y=dy)

    async def return_to_base(self, drone_id: str) -> dict:
        did = self._to_int(drone_id)
        drone = self._world.get_drone(did)
        if drone is None:
            return {"success": False, "drone_id": drone_id}

        result = self._world.command_drone_return(did)
        if "error" in result:
            return {"success": False, "drone_id": drone_id}

        return {
            "success": True,
            "drone_id": drone_id,
            "battery": int(drone.battery),
            "state": "returning",
        }

    async def get_grid_map(self) -> GridMap:
        scanned: set[tuple[int, int]] = set()
        for agent in self._world.agents:
            from simulation.drone_agent import DroneAgent

            if isinstance(agent, DroneAgent):
                scanned.update(agent.visited_cells)

        survivors: list[list[int]] = []
        for agent in self._world.agents:
            from simulation.survivor import SurvivorAgent

            if isinstance(agent, SurvivorAgent) and agent.state.value != "unseen":
                sx, sy = agent._pos()
                survivors.append([sx, sy])

        return GridMap(
            scanned=[list(c) for c in sorted(scanned)],
            survivors=survivors,
        )

    async def broadcast_alert(self, x: int, y: int, message: str) -> dict:
        logger.info("ALERT at (%d, %d): %s", x, y, message)
        return {"success": True, "x": x, "y": y, "message": message}
