import { useEffect, useRef } from "react";
import L from "leaflet";
import type { LatLonTuple } from "../../types/mission";

const DRONE_COLORS = ["#44ff88", "#44aaff", "#ff44aa", "#ffaa44", "#aa44ff"];

export function DroneTraceLayer({
  map,
  traces,
}: {
  map: L.Map;
  traces: Record<string, LatLonTuple[]>;
}) {
  const linesRef = useRef<Record<string, L.Polyline>>({});

  useEffect(() => {
    const seen = new Set<string>();

    Object.entries(traces).forEach(([droneId, positions], idx) => {
      seen.add(droneId);
      if (positions.length < 2) return;

      const latLngs = positions.map((p) => [p[0], p[1]] as L.LatLngTuple);
      const color = DRONE_COLORS[idx % DRONE_COLORS.length];

      if (linesRef.current[droneId]) {
        linesRef.current[droneId].setLatLngs(latLngs);
      } else {
        linesRef.current[droneId] = L.polyline(latLngs, {
          color,
          weight: 2,
          opacity: 0.4,
          dashArray: "6 4",
        }).addTo(map);
      }
    });

    // Remove lines for drones no longer tracked
    Object.keys(linesRef.current).forEach((id) => {
      if (!seen.has(id)) {
        linesRef.current[id]?.remove();
        delete linesRef.current[id];
      }
    });
  }, [map, traces]);

  useEffect(() => {
    return () => {
      Object.values(linesRef.current).forEach((l) => l.remove());
      linesRef.current = {};
    };
  }, [map]);

  return null;
}
