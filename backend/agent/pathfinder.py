"""
Pathfinder — deterministic, no LLM involved.

straight_line_path: Bresenham line from (c0,r0) to (c1,r1).
Returns a list of (col, row) cells the drone will walk through,
excluding the start cell (drone is already there).

The world engine will validate each cell against the grid polygon
and emit OutOfBoundsRejectedEvent for any cell that falls outside.
"""

from __future__ import annotations


def straight_line_path(c0: int, r0: int, c1: int, r1: int) -> list[tuple[int, int]]:
    """Bresenham line from (c0,r0) to (c1,r1), excluding start cell."""
    cells: list[tuple[int, int]] = []
    dc = abs(c1 - c0)
    dr = abs(r1 - r0)
    sc = 1 if c1 > c0 else -1
    sr = 1 if r1 > r0 else -1
    err = dc - dr
    c, r = c0, r0

    while True:
        if c != c0 or r != r0:  # skip start
            cells.append((c, r))
        if c == c1 and r == r1:
            break
        e2 = 2 * err
        if e2 > -dr:
            err -= dr
            c += sc
        if e2 < dc:
            err += dc
            r += sr

    return cells
