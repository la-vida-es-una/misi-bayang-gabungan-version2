"""
Boustrophedon (lawn-mower) coverage path generator.

Given a zone in the grid, generates a coverage plan consisting of:
  - move segments: cell-by-cell paths between scan points
  - scan points: positions where thermal_scan() must be called

The grid.mark_scanned() uses a SQUARE scan pattern: for radius R, each scan
covers a (2R+1) x (2R+1) square centred on the drone position.  With R=5,
each scan covers an 11x11 = 121-cell area.

Spacing = ~70% of scan diameter in both directions, giving ~30% overlap
between adjacent scans to eliminate diagonal gaps.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from agent.pathfinder import straight_line_path
from world.grid import Grid


@dataclass
class CoveragePlan:
    """A segmented coverage plan: move segments interleaved with scan points.

    The drone should execute segments[0], then scan at scan_points[0],
    then segments[1], scan at scan_points[1], etc.
    len(segments) == len(scan_points) + 1 when there's a trailing segment,
    or len(segments) == len(scan_points) when the plan ends with a scan.
    """

    segments: list[list[tuple[int, int]]] = field(default_factory=list)
    scan_points: list[tuple[int, int]] = field(default_factory=list)

    @property
    def total_moves(self) -> int:
        return sum(len(s) for s in self.segments)

    @property
    def flat_path(self) -> list[tuple[int, int]]:
        """Flatten all segments into a single path (for battery estimation)."""
        out: list[tuple[int, int]] = []
        for s in self.segments:
            out.extend(s)
        return out

    @property
    def is_empty(self) -> bool:
        return len(self.scan_points) == 0 and all(len(s) == 0 for s in self.segments)


def generate_coverage_plan(
    grid: Grid,
    zone_id: str,
    scan_radius: int = 5,
    claimed: np.ndarray | None = None,
) -> CoveragePlan:
    """
    Generate a boustrophedon coverage plan for uncovered cells of a zone.

    Returns a CoveragePlan with interleaved move segments and scan points.
    The drone moves through each segment cell-by-cell, then calls
    thermal_scan at the scan point, then moves to the next segment, etc.

    Args:
        claimed: optional bool mask (rows, cols) of cells already claimed
                 by other drones' scan queues — treated as covered.
    """
    zone = grid.get_zone(zone_id)
    if zone is None:
        return CoveragePlan()

    uncovered = zone.mask & ~zone.covered
    if claimed is not None:
        uncovered = uncovered & ~claimed
    if not uncovered.any():
        return CoveragePlan()

    rows, cols = zone.mask.shape
    # Overlap by ~30% to eliminate diagonal gaps between adjacent scans.
    # With radius R, each scan covers 2R+1 cells.  Spacing = 2R+1 would be
    # zero-overlap (touching edges).  We use ceil(0.7 * (2R+1)) so adjacent
    # scans share ~30% of their width, guaranteeing full area coverage.
    effective_diameter = 2 * scan_radius + 1
    line_spacing = max(1, int(0.7 * effective_diameter))
    scan_spacing = max(1, int(0.7 * effective_diameter))

    # Row range with uncovered cells
    row_has_uncovered = np.any(uncovered, axis=1)
    uncovered_rows = np.where(row_has_uncovered)[0]
    if len(uncovered_rows) == 0:
        return CoveragePlan()

    min_row = int(uncovered_rows[0])
    max_row = int(uncovered_rows[-1])

    # Place scan lines offset by scan_radius so the first strip reaches min_row
    first_line = min(min_row + scan_radius, (min_row + max_row) // 2)
    scan_rows = list(range(first_line, max_row + 1, line_spacing))

    # Ensure bottom edge is covered
    if max_row - scan_rows[-1] > scan_radius:
        scan_rows.append(min(max_row, scan_rows[-1] + line_spacing))

    scan_rows = [r for r in scan_rows if 0 <= r < rows]
    if not scan_rows:
        scan_rows = [(min_row + max_row) // 2]

    # Build ordered list of (col, row) scan points along boustrophedon
    all_scan_points: list[tuple[int, int]] = []
    direction = 1  # 1 = left→right, -1 = right→left

    for scan_row in scan_rows:
        band_top = max(0, scan_row - scan_radius)
        band_bot = min(rows, scan_row + scan_radius + 1)
        band = uncovered[band_top:band_bot]
        if not band.any():
            continue

        col_has_cells = np.any(band, axis=0)
        col_indices = np.where(col_has_cells)[0]
        if len(col_indices) == 0:
            continue

        min_col = int(col_indices[0])
        max_col = int(col_indices[-1])

        # Place scan points along this sweep line
        if direction == 1:
            first_col = (
                min_col + scan_radius
                if min_col + scan_radius <= max_col
                else (min_col + max_col) // 2
            )
            sp_cols = list(range(first_col, max_col + 1, scan_spacing))
            if not sp_cols or (max_col - sp_cols[-1] > scan_radius):
                sp_cols.append(
                    min(max_col, (sp_cols[-1] if sp_cols else first_col) + scan_spacing)
                )
        else:
            first_col = (
                max_col - scan_radius
                if max_col - scan_radius >= min_col
                else (min_col + max_col) // 2
            )
            sp_cols = list(range(first_col, min_col - 1, -scan_spacing))
            if not sp_cols or (sp_cols[-1] - min_col > scan_radius):
                sp_cols.append(
                    max(min_col, (sp_cols[-1] if sp_cols else first_col) - scan_spacing)
                )

        # Snap to in-bounds positions
        for col in sp_cols:
            col = max(0, min(cols - 1, col))
            if grid.in_bounds(col, scan_row):
                all_scan_points.append((col, scan_row))
            else:
                # find nearest in-bounds col on this row
                for dc in range(1, scan_radius + 1):
                    if col + dc < cols and grid.in_bounds(col + dc, scan_row):
                        all_scan_points.append((col + dc, scan_row))
                        break
                    if col - dc >= 0 and grid.in_bounds(col - dc, scan_row):
                        all_scan_points.append((col - dc, scan_row))
                        break

        direction *= -1

    if not all_scan_points:
        return CoveragePlan()

    # Build segments: cell-by-cell paths between consecutive scan points
    plan = CoveragePlan()

    # First segment is empty (the approach from drone position → first scan
    # point is prepended by the caller based on drone location).
    plan.segments.append([])
    plan.scan_points.append(all_scan_points[0])

    for i in range(1, len(all_scan_points)):
        prev = all_scan_points[i - 1]
        curr = all_scan_points[i]
        seg = _connect(prev, curr, grid)
        plan.segments.append(seg)
        plan.scan_points.append(curr)

    return plan


def partition_plan(
    plan: CoveragePlan,
    partition_index: int,
    total_partitions: int,
    grid: Grid | None = None,
) -> CoveragePlan:
    """
    Select every Nth scan point from a coverage plan (interleaved partitioning).

    For N drones on the same zone, drone k gets scan points at indices
    k, k+N, k+2N, ...  This spatially distributes drones across the
    boustrophedon pattern from the start.

    Args:
        plan: The full coverage plan to partition.
        partition_index: This drone's index (0-based).
        total_partitions: Total number of drones sharing the zone.
        grid: If provided, uses _connect() for segment paths between
              selected scan points; otherwise uses straight_line_path.

    Returns:
        A new CoveragePlan with the subset of scan points and recomputed
        segments.  Returns an empty plan if this partition has no points.
    """
    if total_partitions <= 1:
        return plan

    selected = plan.scan_points[partition_index::total_partitions]
    if not selected:
        return CoveragePlan()

    out = CoveragePlan()
    # First segment is empty — caller prepends the approach path
    out.segments.append([])
    out.scan_points.append(selected[0])

    for i in range(1, len(selected)):
        prev = selected[i - 1]
        curr = selected[i]
        if grid is not None:
            seg = _connect(prev, curr, grid)
        else:
            seg = straight_line_path(prev[0], prev[1], curr[0], curr[1])
        out.segments.append(seg)
        out.scan_points.append(curr)

    return out


# ── Legacy helper (flat path for backward compat / tests) ────────────────────


def generate_coverage_path(
    grid: Grid,
    zone_id: str,
    scan_radius: int = 5,
) -> list[tuple[int, int]]:
    """
    Legacy wrapper: returns a flat cell-by-cell path covering all scan points.
    Used by tests and the engine's old auto-scan mode.
    """
    plan = generate_coverage_plan(grid, zone_id, scan_radius)
    if plan.is_empty:
        return []

    path: list[tuple[int, int]] = []
    for i, sp in enumerate(plan.scan_points):
        # Add the segment leading to this scan point
        path.extend(plan.segments[i])
        # Add the scan point itself (drone visits it)
        if not path or path[-1] != sp:
            path.append(sp)

    return path


# ── Helpers ───────────────────────────────────────────────────────────────────


def _connect(
    start: tuple[int, int],
    end: tuple[int, int],
    grid: Grid,
) -> list[tuple[int, int]]:
    """
    Cell-by-cell transition from start to end (exclusive of start).
    Uses Bresenham line, filtering for in-bounds cells.
    """
    cells = straight_line_path(start[0], start[1], end[0], end[1])
    return [(c, r) for c, r in cells if grid.in_bounds(c, r)]


def truncate_for_battery(
    path: list[tuple[int, int]],
    drone_battery: float,
    base_pos: tuple[int, int],
    drain_per_move: float = 0.5,
    safety_margin: float = 15.0,
) -> list[tuple[int, int]]:
    """
    Truncate a coverage path to what the drone can safely fly while
    retaining enough battery to return to base.

    At each step, checks: battery_used_so_far + return_cost_from_here.
    Stops when this exceeds available battery minus safety margin.
    """
    if not path:
        return []

    available = drone_battery - safety_margin
    if available <= 0:
        return []

    truncated: list[tuple[int, int]] = []
    for i, (c, r) in enumerate(path):
        cost_so_far = (i + 1) * drain_per_move
        return_dist = abs(c - base_pos[0]) + abs(r - base_pos[1])
        return_cost = return_dist * drain_per_move
        total_cost = cost_so_far + return_cost

        if total_cost > available:
            break

        truncated.append((c, r))

    return truncated


def truncate_plan_for_battery(
    plan: CoveragePlan,
    drone_battery: float,
    drone_pos: tuple[int, int],
    base_pos: tuple[int, int],
    drain_per_move: float = 0.5,
    safety_margin: float = 15.0,
) -> CoveragePlan:
    """
    Truncate a CoveragePlan so the drone can complete it and return to base.

    Walks through segments+scan_points sequentially, tracking cumulative
    battery cost.  Stops before a scan point whose return-to-base cost
    would exceed remaining battery.
    """
    available = drone_battery - safety_margin
    if available <= 0:
        return CoveragePlan()

    out = CoveragePlan()
    cost = 0.0

    for i, sp in enumerate(plan.scan_points):
        seg = plan.segments[i]
        seg_cost = len(seg) * drain_per_move
        # Cost to reach scan point from end of this segment
        if seg:
            last = seg[-1]
        elif out.scan_points:
            last = out.scan_points[-1]
        else:
            last = drone_pos
        approach_to_sp = abs(sp[0] - last[0]) + abs(sp[1] - last[1])
        sp_cost = approach_to_sp * drain_per_move

        # Return cost from scan point to base
        return_dist = abs(sp[0] - base_pos[0]) + abs(sp[1] - base_pos[1])
        return_cost = return_dist * drain_per_move

        total_after = cost + seg_cost + sp_cost + return_cost
        if total_after > available:
            break

        cost += seg_cost + sp_cost
        out.segments.append(seg)
        out.scan_points.append(sp)

    return out
