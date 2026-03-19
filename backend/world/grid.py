"""
Grid — rasterises the master map polygon into a cell index.

Zones are named sub-polygons drawn by the user. Multiple zones can
coexist and be scanned concurrently. Each zone independently tracks
its own coverage mask and status.

Coordinate convention (internal): all geo coords are [lon, lat] (GeoJSON order).
Callers in receiver.py must flip [lat, lon] → [lon, lat] before passing here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Point, shape
from shapely.geometry.polygon import Polygon

from world.models import ZoneStatus


@dataclass
class ZoneState:
    """Per-zone tracking data."""

    zone_id: str
    label: str
    polygon: dict  # original GeoJSON polygon (for serialisation)  # pyright: ignore[reportMissingTypeArgument]
    mask: np.ndarray = field(repr=False)  # bool[rows, cols] — cells in this zone
    covered: np.ndarray = field(repr=False)  # bool[rows, cols] — cells scanned
    status: ZoneStatus = ZoneStatus.IDLE

    @property
    def total_cells(self) -> int:
        return int(self.mask.sum())

    @property
    def covered_cells(self) -> int:
        return int((self.mask & self.covered).sum())

    @property
    def coverage_ratio(self) -> float:
        total = self.total_cells
        if total == 0:
            return 0.0
        return round(self.covered_cells / total, 4)

    @property
    def fully_covered(self) -> bool:
        if not self.mask.any():
            return False
        return bool((self.mask & ~self.covered).sum() == 0)

    def to_dict(self) -> dict:  # pyright: ignore[reportMissingTypeArgument]
        return {
            "zone_id": self.zone_id,
            "label": self.label,
            "status": self.status.value,
            "total_cells": self.total_cells,
            "covered_cells": self.covered_cells,
            "coverage_ratio": self.coverage_ratio,
        }


class Grid:
    def __init__(
        self,
        geojson_polygon: dict[str, object],
        cell_size_m: float = 1.0,
    ) -> None:
        """
        Args:
            geojson_polygon: GeoJSON Polygon geometry (coordinates in [lon, lat]).
            cell_size_m: Cell edge length in the same unit as the polygon coords.
                         For geographic polygons in degrees, use a fractional degree
                         value (e.g. 0.0001 ≈ 11 m at the equator).
                         For test polygons with integer-unit coordinates, use 1.0.
        """
        poly = shape(geojson_polygon)
        if not isinstance(poly, Polygon):
            raise TypeError(f"Expected Polygon, got {type(poly).__name__}")
        self._master: Polygon = poly
        self.cell_size = cell_size_m

        minx, miny, maxx, maxy = self._master.bounds
        self._origin_x = minx
        self._origin_y = miny

        cols = int(np.ceil((maxx - minx) / cell_size_m))
        rows = int(np.ceil((maxy - miny) / cell_size_m))
        # Guard: if the polygon is smaller than one cell in any dimension,
        # treat it as a single cell so the grid is always at least 1×1.
        self.cols = max(1, cols)
        self.rows = max(1, rows)

        # Master mask — True = cell is inside master polygon
        self._master_mask: np.ndarray = self._build_mask(self._master)

        # Multi-zone registry: zone_id → ZoneState
        self._zones: dict[str, ZoneState] = {}

        # Auto-label counter (Zone A, Zone B, …)
        self._label_counter: int = 0

    # ── Zone management ───────────────────────────────────────────────────────

    def add_zone(
        self,
        zone_id: str,
        geojson_polygon: dict[str, object],
        label: str | None = None,
    ) -> ZoneState:
        """
        Register a new search zone. Clips to master polygon.
        Returns the ZoneState.
        """
        poly = shape(geojson_polygon)
        if not isinstance(poly, Polygon):
            raise TypeError(f"Zone must be a Polygon, got {type(poly).__name__}")

        zone_mask = self._build_mask(poly)
        # Clip to master boundary
        zone_mask = zone_mask & self._master_mask

        if label is None:
            label = self._auto_label()

        zone = ZoneState(
            zone_id=zone_id,
            label=label,
            polygon=dict(geojson_polygon),  # store a copy
            mask=zone_mask,
            covered=np.zeros((self.rows, self.cols), dtype=bool),
        )
        self._zones[zone_id] = zone
        return zone

    def remove_zone(self, zone_id: str) -> bool:
        """Remove a zone. Returns True if it existed."""
        return self._zones.pop(zone_id, None) is not None

    def get_zone(self, zone_id: str) -> ZoneState | None:
        return self._zones.get(zone_id)

    def get_all_zones(self) -> dict[str, ZoneState]:
        return dict(self._zones)

    def set_zone_status(self, zone_id: str, status: ZoneStatus) -> bool:
        """Change a zone's status. Returns True if zone exists."""
        zone = self._zones.get(zone_id)
        if zone is None:
            return False
        zone.status = status
        return True

    def get_scanning_zone_ids(self) -> list[str]:
        """Return IDs of all zones currently in SCANNING status."""
        return [
            zid for zid, z in self._zones.items() if z.status == ZoneStatus.SCANNING
        ]

    # ── Coverage tracking ─────────────────────────────────────────────────────

    def mark_scanned(
        self, col: int, row: int, radius: int = 2
    ) -> list[tuple[str, list[tuple[int, int]]]]:
        """
        Mark cells within `radius` of (col, row) as covered in ALL scanning zones.
        Returns list of (zone_id, newly_covered_cells) for each scanning zone
        that had new coverage.
        """
        results: list[tuple[str, list[tuple[int, int]]]] = []
        for zid, zone in self._zones.items():
            if zone.status != ZoneStatus.SCANNING:
                continue
            newly: list[tuple[int, int]] = []
            for dc in range(-radius, radius + 1):
                for dr in range(-radius, radius + 1):
                    c, r = col + dc, row + dr
                    if 0 <= c < self.cols and 0 <= r < self.rows:
                        if zone.mask[r, c] and not zone.covered[r, c]:
                            zone.covered[r, c] = True
                            newly.append((c, r))
            if newly:
                results.append((zid, newly))
        return results

    def zone_fully_covered(self, zone_id: str) -> bool:
        """True when every cell in the specified zone has been scanned."""
        zone = self._zones.get(zone_id)
        if zone is None:
            return False
        return zone.fully_covered

    def coverage_ratio(self, zone_id: str) -> float:
        """Fraction of zone cells covered (0.0 – 1.0)."""
        zone = self._zones.get(zone_id)
        if zone is None:
            return 0.0
        return zone.coverage_ratio

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def in_bounds(self, col: int, row: int) -> bool:
        """True if cell is inside master polygon."""
        if col < 0 or row < 0 or col >= self.cols or row >= self.rows:
            return False
        return bool(self._master_mask[row, col])

    def in_zone(self, col: int, row: int, zone_id: str | None = None) -> bool:
        """
        True if cell is inside a zone.
        If zone_id is given, checks that specific zone.
        If zone_id is None, checks if cell is in ANY zone.
        """
        if col < 0 or row < 0 or col >= self.cols or row >= self.rows:
            return False
        if zone_id is not None:
            zone = self._zones.get(zone_id)
            if zone is None:
                return False
            return bool(zone.mask[row, col])
        return any(bool(z.mask[row, col]) for z in self._zones.values())

    def geo_to_cell(self, lon: float, lat: float) -> tuple[int, int]:
        col = int((lon - self._origin_x) / self.cell_size)
        row = int((lat - self._origin_y) / self.cell_size)
        return col, row

    def cell_to_geo(self, col: int, row: int) -> tuple[float, float]:
        """Returns (lon, lat) centre of cell."""
        lon = self._origin_x + (col + 0.5) * self.cell_size
        lat = self._origin_y + (row + 0.5) * self.cell_size
        return lon, lat

    def all_zone_cells(self, zone_id: str) -> list[tuple[int, int]]:
        zone = self._zones.get(zone_id)
        if zone is None:
            return []
        return [
            (c, r)
            for r in range(self.rows)
            for c in range(self.cols)
            if zone.mask[r, c]
        ]

    def uncovered_zone_cells(self, zone_id: str) -> list[tuple[int, int]]:
        zone = self._zones.get(zone_id)
        if zone is None:
            return []
        return [
            (c, r)
            for r in range(self.rows)
            for c in range(self.cols)
            if zone.mask[r, c] and not zone.covered[r, c]
        ]

    # ── Snapshot ──────────────────────────────────────────────────────────────

    @property
    def bounds(self) -> dict[str, object]:
        zones_info = {zid: z.to_dict() for zid, z in self._zones.items()}
        scanning_ids = self.get_scanning_zone_ids()
        # Aggregate coverage across all scanning zones
        total_scanning_cells = sum(
            self._zones[zid].total_cells for zid in scanning_ids if zid in self._zones
        )
        covered_scanning_cells = sum(
            self._zones[zid].covered_cells for zid in scanning_ids if zid in self._zones
        )
        aggregate_ratio = (
            round(covered_scanning_cells / total_scanning_cells, 4)
            if total_scanning_cells > 0
            else 0.0
        )

        return {
            "cols": self.cols,
            "rows": self.rows,
            "cell_size_m": self.cell_size,
            "master_cells": int(self._master_mask.sum()),
            "zone_count": len(self._zones),
            "zones": zones_info,
            "scanning_coverage_ratio": aggregate_ratio,
        }

    # ── Private ───────────────────────────────────────────────────────────────

    def _build_mask(self, poly: Polygon) -> np.ndarray:
        """
        Use poly.covers() instead of poly.contains() so that cell centres
        exactly on the polygon boundary are included. This is important when
        the grid origin aligns with a polygon corner (common for axis-aligned
        rectangles drawn by the user).
        """
        mask = np.zeros((self.rows, self.cols), dtype=bool)
        for r in range(self.rows):
            for c in range(self.cols):
                lon, lat = self.cell_to_geo(c, r)
                if poly.covers(Point(lon, lat)):
                    mask[r, c] = True
        return mask

    def _auto_label(self) -> str:
        """Generate labels: Zone A, Zone B, …, Zone Z, Zone AA, …"""
        idx = self._label_counter
        self._label_counter += 1
        if idx < 26:
            return f"Zone {chr(65 + idx)}"
        # For >26 zones: Zone AA, Zone AB, etc.
        first = chr(65 + (idx // 26) - 1)
        second = chr(65 + (idx % 26))
        return f"Zone {first}{second}"
