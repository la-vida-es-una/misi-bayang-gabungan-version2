import { useEffect, useRef } from "react";
import L from "leaflet";
import type { SurvivorState } from "../../types/mission";


function survivorIcon(status: "missing" | "found"): L.DivIcon {
  const found = status === "found";
  return L.divIcon({
    className: "",
    html: `
      <div style="
        width:14px;height:14px;border-radius:50%;
        background:${found ? "#ff4444" : "#556677"};
        border:2px solid ${found ? "#ff8888" : "#334455"};
        box-shadow:${found ? "0 0 8px rgba(255,68,68,.7)" : "none"};
      "></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

export function SurvivorMarkerLayer({
  map,
  survivors,
}: {
  map: L.Map;
  survivors: Record<string, SurvivorState>;
}) {
  const markersRef = useRef<Record<string, L.Marker>>({});

  useEffect(() => {
    const seen = new Set<string>();

    Object.entries(survivors).forEach(([id, s]) => {
      seen.add(id);
      if (markersRef.current[id]) {
        markersRef.current[id].setIcon(survivorIcon(s.status));
      } else {
        const m = L.marker([s.lat, s.lon], { icon: survivorIcon(s.status) })
          .addTo(map)
          .bindTooltip(id, { permanent: false, direction: "top" });
        markersRef.current[id] = m;
      }
    });

    Object.keys(markersRef.current).forEach((id) => {
      if (!seen.has(id)) {
        markersRef.current[id]?.remove();
        delete markersRef.current[id];
      }
    });
  }, [map, survivors]);

  useEffect(() => {
    return () => {
      Object.values(markersRef.current).forEach((m) => m.remove());
      markersRef.current = {};
    };
  }, [map]);

  return null;
}
