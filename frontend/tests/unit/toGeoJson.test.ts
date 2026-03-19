/**
 * Unit tests — toGeoJSON ring closure
 *
 * toGeoJSON converts [lat,lon] tuple arrays into a GeoJSON Polygon.
 * The only non-trivial behaviour is ring closure:
 *   - If the first and last point differ, the first point is appended.
 *   - If already closed, no duplicate is added.
 *
 * Run: bun test tests/unit/toGeoJSON.test.ts
 */

import { describe, test, expect } from "bun:test";

type LatLonTuple = [number, number];

interface GeoJSONPolygon {
  type: "Polygon";
  coordinates: LatLonTuple[][];
}

// Mirror of toGeoJSON in useMission.ts
function toGeoJSON(points: LatLonTuple[]): GeoJSONPolygon {
  if (points.length === 0) return { type: "Polygon", coordinates: [[]] };
  const ring = [...points];
  const first = ring[0]!;
  const last = ring[ring.length - 1]!;
  if (first[0] !== last[0] || first[1] !== last[1]) {
    ring.push(first);
  }
  return { type: "Polygon", coordinates: [ring] };
}

// ── Basic structure ───────────────────────────────────────────────────────────

describe("toGeoJSON — basic structure", () => {
  test("returns a GeoJSON Polygon type", () => {
    const result = toGeoJSON([[0, 0], [1, 0], [1, 1]]);
    expect(result.type).toBe("Polygon");
  });

  test("wraps coordinates in a single ring array", () => {
    const result = toGeoJSON([[0, 0], [1, 0], [1, 1]]);
    expect(result.coordinates).toHaveLength(1);
    expect(Array.isArray(result.coordinates[0])).toBe(true);
  });

  test("preserves original points", () => {
    const pts: LatLonTuple[] = [[3.314, 117.591], [3.315, 117.592], [3.316, 117.591]];
    const result = toGeoJSON(pts);
    const ring = result.coordinates[0]!;
    expect(ring[0]).toEqual([3.314, 117.591]);
    expect(ring[1]).toEqual([3.315, 117.592]);
    expect(ring[2]).toEqual([3.316, 117.591]);
  });
});

// ── Ring closure ──────────────────────────────────────────────────────────────

describe("toGeoJSON — ring closure", () => {
  test("closes open ring by appending first point", () => {
    const pts: LatLonTuple[] = [[0, 0], [1, 0], [1, 1], [0, 1]];
    const result = toGeoJSON(pts);
    const ring = result.coordinates[0]!;
    // Ring should be closed: last point === first point
    expect(ring[ring.length - 1]).toEqual(ring[0]);
  });

  test("closed ring has length = original + 1", () => {
    const pts: LatLonTuple[] = [[0, 0], [1, 0], [1, 1], [0, 1]];
    const result = toGeoJSON(pts);
    expect(result.coordinates[0]).toHaveLength(pts.length + 1);
  });

  test("does NOT add duplicate if ring is already closed", () => {
    const pts: LatLonTuple[] = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]; // last === first
    const result = toGeoJSON(pts);
    expect(result.coordinates[0]).toHaveLength(pts.length); // no extra point
  });

  test("last point equals first point after closure", () => {
    const pts: LatLonTuple[] = [[3.314, 117.591], [3.315, 117.592], [3.316, 117.591]];
    const result = toGeoJSON(pts);
    const ring = result.coordinates[0]!;
    expect(ring[ring.length - 1]).toEqual(pts[0]);
  });

  test("already-closed polygon is returned unchanged", () => {
    const pts: LatLonTuple[] = [[1, 2], [3, 4], [5, 6], [1, 2]];
    const result = toGeoJSON(pts);
    const ring = result.coordinates[0]!;
    expect(ring).toHaveLength(4);
    expect(ring[0]).toEqual(ring[3]);
  });
});

// ── Edge cases ────────────────────────────────────────────────────────────────

describe("toGeoJSON — edge cases", () => {
  test("minimum valid polygon (3 points) gets closed to 4", () => {
    const pts: LatLonTuple[] = [[0, 0], [1, 0], [0, 1]];
    const result = toGeoJSON(pts);
    const ring = result.coordinates[0]!;
    expect(ring).toHaveLength(4);
    expect(ring[3]).toEqual([0, 0]);
  });

  test("does not mutate the original array", () => {
    const pts: LatLonTuple[] = [[0, 0], [1, 0], [1, 1]];
    const original = [...pts];
    toGeoJSON(pts);
    expect(pts).toHaveLength(original.length);
    expect(pts[0]).toEqual(original[0]);
  });

  test("handles negative coordinates (southern hemisphere)", () => {
    const pts: LatLonTuple[] = [[-6.91, 107.62], [-6.92, 107.63], [-6.91, 107.64]];
    const result = toGeoJSON(pts);
    const ring = result.coordinates[0]!;
    expect(ring[ring.length - 1]).toEqual(pts[0]);
  });

  test("handles coordinates that are very close but not equal", () => {
    // Floating point pitfall: 0.1 + 0.2 !== 0.3
    // Two points that look the same but differ at float precision
    const pts: LatLonTuple[] = [[0.1, 0.2], [1.0, 0.0], [0.1 + 0.2, 0.3]];
    // This should NOT close if floating point differs
    // We just verify it doesn't throw
    expect(() => toGeoJSON(pts)).not.toThrow();
  });

  test("single-coordinate rectangle from sim boundary (4 corners) gets closed to 5", () => {
    const rect: LatLonTuple[] = [
      [3.31, 117.57],
      [3.31, 117.59],
      [3.33, 117.59],
      [3.33, 117.57],
    ];
    const result = toGeoJSON(rect);
    const ring = result.coordinates[0]!;
    expect(ring).toHaveLength(5);
    expect(ring[4]).toEqual([3.31, 117.57]);
  });

  test("polygon drawn on map (5+ points) closes correctly", () => {
    const poly: LatLonTuple[] = [
      [3.32378, 117.57555],
      [3.30925, 117.57680],
      [3.30591, 117.59495],
      [3.31975, 117.60203],
      [3.32489, 117.58942],
    ];
    const result = toGeoJSON(poly);
    const ring = result.coordinates[0]!;
    expect(ring).toHaveLength(poly.length + 1);
    expect(ring[ring.length - 1]).toEqual(poly[0]);
  });
});
