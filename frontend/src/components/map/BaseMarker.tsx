import { useEffect, useRef } from "react";
import L from "leaflet";

export function BaseMarker({
  map, lat, lon,
}: { map: L.Map; lat: number; lon: number }) {
  const markerRef = useRef<L.Marker | null>(null);

  useEffect(() => {
    markerRef.current?.remove();
    markerRef.current = L.marker([lat, lon], {
      icon: L.divIcon({
        className: "",
        html: `
          <div style="
            width:20px;height:20px;border-radius:50%;
            background:#ffaa44;border:2px solid #fff;
            box-shadow:0 0 12px rgba(255,170,68,.6);
            display:flex;align-items:center;justify-content:center;
            font-size:10px;color:#fff;font-weight:bold;
          ">B</div>`,
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      }),
    })
      .addTo(map)
      .bindTooltip("Base", { permanent: false, direction: "top" });

    return () => { markerRef.current?.remove(); };
  }, [map, lat, lon]);

  return null;
}
