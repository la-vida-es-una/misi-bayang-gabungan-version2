"""
Shared context for the MCP server.

This module holds the FastMCP application instance and the simulation world
singleton to avoid circular dependencies between the main server entry point
and the tool/resource modules.
"""

from __future__ import annotations

from fastmcp import FastMCP
from simulation import SARWorld
from config.settings import get_settings

# ---------------------------------------------------------------------------
# Shared simulation singleton — dimensions driven by settings
# ---------------------------------------------------------------------------
_settings = get_settings()
_size = _settings.GRID_SIZE

world: SARWorld = SARWorld(
    n_drones=5,
    n_survivors=6,
    width=_size,
    height=_size,
    n_obstacles=3,
    vision_radius=max(2.0, _size * 0.08),
    battery_drain=0.9,
    low_battery=20.0,
    speed=1.0,
    seed=None,
)


def set_world(new_world: SARWorld) -> None:
    """
    Replace the module-level world used by all MCP tool modules.

    Call this before starting a new mission so that MCP tools operate
    on the freshly created SARWorld instance rather than the default
    singleton.
    """
    global world
    world = new_world

# ---------------------------------------------------------------------------
# FastMCP app
# ---------------------------------------------------------------------------
mcp: FastMCP = FastMCP(
    name="Misi Bayang — SAR Drone Control",
    instructions=(
        f"You control a swarm of search-and-rescue drones over a {_size}×{_size} grid. "
        "Use the tools to move drones, thermal-scan for survivors, and recall "
        "drones when their battery is low. Call step(N) after move_to to advance "
        "the simulation so drones physically travel to their waypoints."
    ),
)
