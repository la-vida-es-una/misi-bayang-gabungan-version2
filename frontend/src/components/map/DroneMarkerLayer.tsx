import { useEffect, useRef } from "react";
import L from "leaflet";
import type { DroneState } from "../../types/mission";

function batteryColor(pct: number): string {
  if (pct > 50) return "#44ff88";
  if (pct > 25) return "#ffaa44";
  return "#ff4444";
}

function droneIcon(id: string, drone: DroneState): L.DivIcon {
  const color = batteryColor(drone.battery);
  const label = id.replace(/[^0-9]/g, "") || id.slice(-1).toUpperCase();
  return L.divIcon({
    className: "",
    html: `
      <div style="position:relative;width:28px;height:28px;">
        <div style="
          width:28px;height:28px;border-radius:50%;
          background:#0a1423;border:2px solid ${color};
          box-shadow:0 0 10px ${color}66;
          display:flex;align-items:center;justify-content:center;
          font-size:10px;font-weight:bold;color:${color};
        ">${label}</div>
        <div style="
          position:absolute;bottom:-4px;left:50%;transform:translateX(-50%);
          width:20px;height:3px;background:#333;border-radius:2px;overflow:hidden;
        ">
          <div style="width:${drone.battery}%;height:100%;background:${color};transition:width .3s"></div>
        </div>
      </div>`,
    iconSize: [28, 32],
    iconAnchor: [14, 14],
  });
}

export function DroneMarkerLayer({
  map,
  drones,
}: {
  map: L.Map;
  drones: Record<string, DroneState>;
}) {
  const markersRef = useRef<Record<string, L.Marker>>({});

  useEffect(() => {
    const seen = new Set<string>();

    Object.entries(drones).forEach(([id, drone]) => {
      seen.add(id);
      const pos: L.LatLngExpression = [drone.lat, drone.lon];
      if (markersRef.current[id]) {
        markersRef.current[id].setLatLng(pos);
        markersRef.current[id].setIcon(droneIcon(id, drone));
      } else {
        const m = L.marker(pos, { icon: droneIcon(id, drone) })
          .addTo(map)
          .bindTooltip(id, { permanent: false, direction: "top" });
        markersRef.current[id] = m;
      }
    });

    // Remove markers for drones no longer in snapshot
    Object.keys(markersRef.current).forEach((id) => {
      if (!seen.has(id)) {
        markersRef.current[id]?.remove();
        delete markersRef.current[id];
      }
    });
  }, [map, drones]);

  // Cleanup all on unmount
  useEffect(() => {
    return () => {
      Object.values(markersRef.current).forEach((m) => m.remove());
      markersRef.current = {};
    };
  }, [map]);

  return null;
}
