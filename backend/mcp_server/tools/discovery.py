"""
Discovery tools — enumerate drones and inspect individual drone status.
"""

from __future__ import annotations

import mcp_server.context as context


@context.mcp.tool()
def list_active_drones() -> dict:
    """
    List all drones that still have battery remaining.

    Returns
    -------
    dict
        ``{"drones": ["drone_0", "drone_1", ...]}``
        where each entry is the string ID of an active drone.
    """
    active = context.world.list_active_drones()
    return {"drones": [f"drone_{d['id']}" for d in active]}


@context.mcp.tool()
def get_battery_status(drone_id: str) -> dict:
    """
    Return the status snapshot of a single drone including battery level.

    Parameters
    ----------
    drone_id : str
        String ID of the drone to inspect, e.g. ``"drone_0"``.

    Returns
    -------
    dict
        ``{"drone_id": str, "battery": float, "x": int, "y": int, "state": str}``
        Returns ``{"error": "..."}`` if the drone is not found.
    """
    uid = int(drone_id.split("_")[1])
    drone = context.world.get_drone(uid)
    if drone is None:
        return {"error": f"drone {drone_id} not found"}
    d = drone.to_dict()
    return {
        "drone_id": drone_id,
        "battery": d["battery"],
        "x": d["x"],
        "y": d["y"],
        "state": d["state"],
    }
