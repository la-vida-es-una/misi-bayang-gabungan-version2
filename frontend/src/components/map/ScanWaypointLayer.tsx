import { useEffect, useRef } from "react";
import L from "leaflet";
import type { LatLonTuple } from "../../types/mission";

const DRONE_COLORS = ["#44ff88", "#44aaff", "#ff44aa", "#ffaa44", "#aa44ff"];
const SCAN_RADIUS_CELLS = 5;
/** Approximate meters per degree of latitude */
const DEG_TO_METERS = 111_320;

export function ScanWaypointLayer({
  map,
  waypoints,
  cellSizeDeg,
}: {
  map: L.Map;
  waypoints: Record<string, LatLonTuple[]>;
  /** Grid cell size in degrees (from snapshot.grid.cell_size_m) */
  cellSizeDeg?: number;
}) {
  const markersRef = useRef<Record<string, L.CircleMarker[]>>({});
  const linesRef = useRef<Record<string, L.Polyline>>({});
  const circlesRef = useRef<Record<string, L.Circle[]>>({});

  useEffect(() => {
    const seen = new Set<string>();

    Object.entries(waypoints).forEach(([droneId, positions], idx) => {
      seen.add(droneId);
      const color = DRONE_COLORS[idx % DRONE_COLORS.length];

      // Clean old markers for this drone
      markersRef.current[droneId]?.forEach((m) => m.remove());
      markersRef.current[droneId] = positions.map((p) =>
        L.circleMarker([p[0], p[1]], {
          radius: 4,
          color,
          fillColor: color,
          fillOpacity: 0.8,
          weight: 1,
        }).addTo(map)
      );

      // Scan area circles at each waypoint
      circlesRef.current[droneId]?.forEach((c) => c.remove());
      if (cellSizeDeg && cellSizeDeg > 0) {
        const radiusMeters = SCAN_RADIUS_CELLS * cellSizeDeg * DEG_TO_METERS;
        circlesRef.current[droneId] = positions.map((p) =>
          L.circle([p[0], p[1]], {
            radius: radiusMeters,
            color,
            fillColor: color,
            fillOpacity: 0.06,
            weight: 1,
            opacity: 0.25,
          }).addTo(map)
        );
      } else {
        circlesRef.current[droneId] = [];
      }

      // Connecting line
      if (positions.length >= 2) {
        const latLngs = positions.map((p) => [p[0], p[1]] as L.LatLngTuple);
        if (linesRef.current[droneId]) {
          linesRef.current[droneId].setLatLngs(latLngs);
        } else {
          linesRef.current[droneId] = L.polyline(latLngs, {
            color,
            weight: 2,
            opacity: 0.7,
          }).addTo(map);
        }
      }
    });

    // Remove for drones no longer tracked
    Object.keys(markersRef.current).forEach((id) => {
      if (!seen.has(id)) {
        markersRef.current[id]?.forEach((m) => m.remove());
        delete markersRef.current[id];
        linesRef.current[id]?.remove();
        delete linesRef.current[id];
        circlesRef.current[id]?.forEach((c) => c.remove());
        delete circlesRef.current[id];
      }
    });
  }, [map, waypoints, cellSizeDeg]);

  useEffect(() => {
    return () => {
      Object.values(markersRef.current).forEach((arr) => arr.forEach((m) => m.remove()));
      markersRef.current = {};
      Object.values(linesRef.current).forEach((l) => l.remove());
      linesRef.current = {};
      Object.values(circlesRef.current).forEach((arr) => arr.forEach((c) => c.remove()));
      circlesRef.current = {};
    };
  }, [map]);

  return null;
}
