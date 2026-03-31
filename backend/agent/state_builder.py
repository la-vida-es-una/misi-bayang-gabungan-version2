"""
State Builder — constructs compact mission state summaries for LLM context injection.

This module solves the context loss problem where the LLM forgets mission state
after the conversation history sliding window truncates older messages.

Instead of relying on chat history, we inject authoritative state from WorldEngine
at the start of every LLM invocation (~300 tokens, fixed cost regardless of mission length).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from world.engine import WorldEngine


@dataclass
class MissionStateSummary:
    """Compact representation of mission state for LLM context injection."""

    tick: int
    drones: list[dict[str, Any]]
    zones: list[dict[str, Any]]
    survivors_found: int
    survivors_total: int
    recent_events: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        """Format as compact text block for system prompt injection."""
        lines = [f"[MISSION STATE - tick {self.tick}]", "", "DRONES:"]

        for d in self.drones:
            zone_info = f", zone={d['zone']}" if d.get("zone") else ", unassigned"
            scans = f", {d['scans_left']} scans left" if d.get("scans_left") else ""
            lines.append(
                f"- {d['id']}: {d['battery']}% battery, {d['status']}{zone_info}{scans}"
            )

        lines.extend(["", "ZONES:"])
        for z in self.zones:
            lines.append(f"- {z['label']}: {z['coverage']}% covered, {z['status']}")

        lines.extend(
            [
                "",
                f"SURVIVORS: {self.survivors_found} found / {self.survivors_total} total",
            ]
        )

        if self.recent_events:
            lines.extend(["", "RECENT EVENTS:"])
            for ev in self.recent_events[-5:]:
                lines.append(f"- {ev}")

        return "\n".join(lines)


def build_mission_state_summary(
    engine: "WorldEngine",
    tick: int,
    recent_events: list[dict[str, Any]] | None = None,
) -> MissionStateSummary:
    """
    Build a compact state summary from WorldEngine for LLM context injection.

    Args:
        engine: The WorldEngine instance with authoritative state
        tick: Current simulation tick
        recent_events: Optional list of recent key events with 'tick' and 'summary' keys

    Returns:
        MissionStateSummary ready to be formatted via to_prompt_block()
    """
    state = engine.get_world_state()
    zones_data = engine.get_zones()
    assignments = engine.get_drone_assignments()
    found, total = engine.get_survivor_counts()

    drones = []
    for did, d in state["drones"].items():
        scans_left = len(engine._drone_scan_queue.get(did, []))
        drones.append(
            {
                "id": did,
                "battery": round(d["battery"], 1),
                "status": d["status"],
                "zone": assignments.get(did),
                "scans_left": scans_left,
            }
        )

    zones = []
    for zid, z in zones_data.items():
        zones.append(
            {
                "id": zid,
                "label": z.get("label", zid),
                "coverage": round(z.get("coverage_ratio", 0) * 100, 1),
                "status": z.get("status", "idle"),
            }
        )

    event_strs = []
    if recent_events:
        for ev in recent_events[-5:]:
            event_strs.append(f"tick {ev['tick']}: {ev['summary']}")

    return MissionStateSummary(
        tick=tick,
        drones=drones,
        zones=zones,
        survivors_found=found,
        survivors_total=total,
        recent_events=event_strs,
    )
