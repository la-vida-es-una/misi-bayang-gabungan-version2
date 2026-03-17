"""
Battery / emergency tools — recall drones and broadcast survivor alerts.
"""

from __future__ import annotations

import mcp_server.context as context


@context.mcp.tool()
def return_to_base(drone_id: str) -> dict:
    """
    Command a drone to return to the charging base.

    The drone's state is set to RETURN and it will fly back at its
    configured speed over subsequent simulation ticks. Battery is recharged
    automatically when the drone arrives at base.

    Parameters
    ----------
    drone_id : str
        String ID of the drone to recall, e.g. ``"drone_0"``.

    Returns
    -------
    dict
        Updated drone snapshot, or ``{"error": "..."}`` if the drone
        does not exist.
    """
    uid = int(drone_id.split("_")[1])
    return context.world.command_drone_return(uid)


@context.mcp.tool()
def broadcast_alert(x: int, y: int, message: str) -> dict:
    """
    Broadcast a survivor alert to all units at the given coordinates.

    Parameters
    ----------
    x, y : int
        Grid coordinates of the alert.
    message : str
        Human-readable alert description.

    Returns
    -------
    dict
        ``{"success": True, "x": int, "y": int, "message": str}``
    """
    if not hasattr(context.world, "_alerts"):
        context.world._alerts = []  # type: ignore[attr-defined]
    context.world._alerts.append(  # type: ignore[attr-defined]
        {"x": x, "y": y, "message": message, "tick": context.world.steps}
    )
    return {"success": True, "x": x, "y": y, "message": message}
