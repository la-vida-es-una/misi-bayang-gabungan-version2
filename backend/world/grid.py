"""
Grid — rasterises the master map polygon into a 1 m² cell index.

Zones are sub-polygons drawn by the user after map definition.
Each zone tracks which of its cells have been scanned (coverage).

Coordinate convention (internal): all geo coords are [lon, lat] (GeoJSON order).
Callers in receiver.py must flip [lat, lon] → [lon, lat] before passing here.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import Point, shape
from shapely.geometry.polygon import Polygon


class Grid:
    def __init__(
        self,
        geojson_polygon: dict[str, object],
        cell_size_m: float = 1.0,
    ) -> None:
        """
        Args:
            geojson_polygon: GeoJSON Polygon geometry (coordinates in [lon, lat]).
            cell_size_m: Cell edge length in metres.
        """
        poly = shape(geojson_polygon)
        if not isinstance(poly, Polygon):
            raise TypeError(f"Expected Polygon, got {type(poly).__name__}")
        self._master: Polygon = poly
        self.cell_size = cell_size_m

        minx, miny, maxx, maxy = self._master.bounds
        self._origin_x = minx
        self._origin_y = miny

        self.cols = int(np.ceil((maxx - minx) / cell_size_m))
        self.rows = int(np.ceil((maxy - miny) / cell_size_m))

        # Master mask — True = cell is inside master polygon
        self._master_mask: np.ndarray = self._build_mask(self._master)

        # Active zone mask — cells in the current drawable zone
        self._zone_mask: np.ndarray = np.zeros((self.rows, self.cols), dtype=bool)

        # Coverage mask — cells scanned (drone within scan radius)
        self._covered_mask: np.ndarray = np.zeros((self.rows, self.cols), dtype=bool)

        # Zone index (increments each time set_zone() is called)
        self.zone_index: int = 0

    # ── Zone management ───────────────────────────────────────────────────────

    def set_zone(self, geojson_polygon: dict[str, object]) -> dict[str, int]:
        """
        Set the active search zone. Must be a subset of the master polygon.
        Resets coverage for the new zone.
        Returns zone cell count.
        """
        poly = shape(geojson_polygon)
        if not isinstance(poly, Polygon):
            raise TypeError(f"Zone must be a Polygon, got {type(poly).__name__}")

        zone_mask = self._build_mask(poly)
        # Clip to master boundary
        self._zone_mask = zone_mask & self._master_mask
        # Reset coverage only for cells in this new zone
        self._covered_mask[self._zone_mask] = False
        self.zone_index += 1

        return {
            "zone_index": self.zone_index,
            "zone_cells": int(self._zone_mask.sum()),
        }

    # ── Coverage tracking ─────────────────────────────────────────────────────

    def mark_scanned(self, col: int, row: int, radius: int = 2) -> list[tuple[int, int]]:
        """
        Mark all zone cells within `radius` of (col, row) as covered.
        Returns newly covered cells.
        """
        newly: list[tuple[int, int]] = []
        for dc in range(-radius, radius + 1):
            for dr in range(-radius, radius + 1):
                c, r = col + dc, row + dr
                if 0 <= c < self.cols and 0 <= r < self.rows:
                    if self._zone_mask[r, c] and not self._covered_mask[r, c]:
                        self._covered_mask[r, c] = True
                        newly.append((c, r))
        return newly

    def zone_fully_covered(self) -> bool:
        """True when every cell in the active zone has been scanned."""
        if not self._zone_mask.any():
            return False
        return bool((self._zone_mask & ~self._covered_mask).sum() == 0)

    def coverage_ratio(self) -> float:
        """Fraction of zone cells covered (0.0 – 1.0)."""
        total = int(self._zone_mask.sum())
        if total == 0:
            return 0.0
        covered = int((self._zone_mask & self._covered_mask).sum())
        return round(covered / total, 4)

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def in_bounds(self, col: int, row: int) -> bool:
        """True if cell is inside master polygon."""
        if col < 0 or row < 0 or col >= self.cols or row >= self.rows:
            return False
        return bool(self._master_mask[row, col])

    def in_zone(self, col: int, row: int) -> bool:
        """True if cell is inside the active zone."""
        if col < 0 or row < 0 or col >= self.cols or row >= self.rows:
            return False
        return bool(self._zone_mask[row, col])

    def geo_to_cell(self, lon: float, lat: float) -> tuple[int, int]:
        col = int((lon - self._origin_x) / self.cell_size)
        row = int((lat - self._origin_y) / self.cell_size)
        return col, row

    def cell_to_geo(self, col: int, row: int) -> tuple[float, float]:
        """Returns (lon, lat) centre of cell."""
        lon = self._origin_x + (col + 0.5) * self.cell_size
        lat = self._origin_y + (row + 0.5) * self.cell_size
        return lon, lat

    def all_zone_cells(self) -> list[tuple[int, int]]:
        return [(c, r) for r in range(self.rows) for c in range(self.cols) if self._zone_mask[r, c]]

    def uncovered_zone_cells(self) -> list[tuple[int, int]]:
        return [
            (c, r)
            for r in range(self.rows)
            for c in range(self.cols)
            if self._zone_mask[r, c] and not self._covered_mask[r, c]
        ]

    # ── Snapshot ──────────────────────────────────────────────────────────────

    @property
    def bounds(self) -> dict[str, object]:
        return {
            "cols": self.cols,
            "rows": self.rows,
            "cell_size_m": self.cell_size,
            "master_cells": int(self._master_mask.sum()),
            "zone_index": self.zone_index,
            "zone_cells": int(self._zone_mask.sum()),
            "covered_cells": int((self._zone_mask & self._covered_mask).sum()),
            "coverage_ratio": self.coverage_ratio(),
        }

    # ── Private ───────────────────────────────────────────────────────────────

    def _build_mask(self, poly: Polygon) -> np.ndarray:
        mask = np.zeros((self.rows, self.cols), dtype=bool)
        for r in range(self.rows):
            for c in range(self.cols):
                lon, lat = self.cell_to_geo(c, r)
                if poly.contains(Point(lon, lat)):
                    mask[r, c] = True
        return mask
