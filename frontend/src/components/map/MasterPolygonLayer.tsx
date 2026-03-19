import { useEffect, useRef } from "react";
import L from "leaflet";
import type { LatLonTuple } from "../../types/mission";

export function MasterPolygonLayer({
  map,
  points,
  color = "#44aaff",
}: {
  map: L.Map;
  points: LatLonTuple[];
  color?: string;
}) {
  const layerRef = useRef<L.Polygon | null>(null);

  useEffect(() => {
    layerRef.current?.remove();
    if (points.length < 3) return;
    layerRef.current = L.polygon(points, {
      color,
      fillColor: color,
      fillOpacity: 0.06,
      weight: 1.5,
      dashArray: "4 4",
    }).addTo(map);
    return () => { layerRef.current?.remove(); };
  }, [map, points, color]);

  return null;
}
