"""
Boustrophedon (lawn-mower) coverage path generator.

Given a zone in the grid, generates a cell-by-cell path that, when combined
with auto-scanning (square pattern, radius=5) at each position, guarantees
100% coverage of the zone.

The grid.mark_scanned() uses a SQUARE scan pattern: for radius R, each scan
covers a (2R+1) x (2R+1) square centred on the drone position. With R=5,
each scan covers an 11x11 = 121-cell area.

Line spacing = 2*R cells between parallel scan lines. This gives exactly
1 cell of overlap between adjacent scan strips, guaranteeing no gaps.

For a typical 25x25 grid with R=5: 3 scan lines × 25 cols ≈ 85 moves,
costing ~42% battery. Easily feasible for a single drone.
"""

from __future__ import annotations

import numpy as np

from agent.pathfinder import straight_line_path
from world.grid import Grid


def generate_coverage_path(
    grid: Grid,
    zone_id: str,
    scan_radius: int = 5,
) -> list[tuple[int, int]]:
    """
    Generate a boustrophedon coverage path for uncovered cells of a zone.

    Returns a cell-by-cell path: list of (col, row) positions.
    The drone visits each position one per tick. Combined with auto-scanning
    (square pattern, scan_radius) at every position, this guarantees 100%
    coverage.

    Line spacing = 2 * scan_radius (e.g. 10 for R=5).
    """
    zone = grid.get_zone(zone_id)
    if zone is None:
        return []

    uncovered = zone.mask & ~zone.covered
    if not uncovered.any():
        return []

    rows, cols = zone.mask.shape
    line_spacing = max(1, 2 * scan_radius)  # 10 for radius 5

    # Find row range with uncovered cells
    row_has_uncovered = np.any(uncovered, axis=1)
    uncovered_rows = np.where(row_has_uncovered)[0]
    if len(uncovered_rows) == 0:
        return []

    min_row = int(uncovered_rows[0])
    max_row = int(uncovered_rows[-1])

    # Place scan lines so their scan strips cover all uncovered rows.
    # First line: offset by half the scan width into the uncovered region
    # so the scan strip reaches back to min_row.
    first_line = min(min_row + scan_radius, (min_row + max_row) // 2)
    scan_rows = list(range(first_line, max_row + 1, line_spacing))

    # Ensure the bottom edge is covered
    if max_row - scan_rows[-1] > scan_radius:
        scan_rows.append(min(max_row, scan_rows[-1] + line_spacing))

    # Clamp to grid bounds
    scan_rows = [r for r in scan_rows if 0 <= r < rows]
    if not scan_rows:
        # Fallback: use the middle of the uncovered region
        scan_rows = [(min_row + max_row) // 2]

    path: list[tuple[int, int]] = []
    direction = 1  # 1 = left-to-right, -1 = right-to-left

    for scan_row in scan_rows:
        # Find column range: look at the band of rows this scan line covers
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

        # Generate horizontal sweep for this scan line
        line_cells: list[tuple[int, int]] = []
        if direction == 1:
            for col in range(min_col, max_col + 1):
                if grid.in_bounds(col, scan_row):
                    line_cells.append((col, scan_row))
        else:
            for col in range(max_col, min_col - 1, -1):
                if grid.in_bounds(col, scan_row):
                    line_cells.append((col, scan_row))

        if not line_cells:
            continue

        # Connect from previous path end to this line start
        if path:
            transition = _connect(path[-1], line_cells[0], grid)
            path.extend(transition)

        path.extend(line_cells)
        direction *= -1

    return path


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
