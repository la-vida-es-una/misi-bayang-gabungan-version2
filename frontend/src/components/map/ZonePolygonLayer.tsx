/**
 * ZonePolygonLayer -- renders all committed zones on the map.
 *
 * Each zone is drawn as a polygon with its assigned color.
 * Selected zones have a highlighted border.
 * Scanning zones have a solid border; idle zones have dashed.
 * Labels are shown as tooltips.
 * Click on a zone to select it (shift+click for additive).
 */

import { useEffect, useRef } from "react";
import L from "leaflet";
import { useMissionContext } from "../../context/MissionContext";
import { useMission } from "../../hooks/useMission";
import type { ZoneClientState } from "../../types/mission";

export function ZonePolygonLayer({ map }: { map: L.Map }) {
  const { state, selectZone, clearZoneSelection, removePendingZone } = useMissionContext();
  const { scanZones, stopScanning, removeZone } = useMission();
  const layersRef = useRef<Record<string, L.Polygon>>({});
  const pendingLayersRef = useRef<L.Polygon[]>([]);
  const contextMenuRef = useRef<L.Popup | null>(null);

  useEffect(() => {
    const seen = new Set<string>();

    Object.values(state.zones).forEach((zone: ZoneClientState) => {
      seen.add(zone.zone_id);
      const existing = layersRef.current[zone.zone_id];

      const style: L.PathOptions = {
        color: zone.color,
        fillColor: zone.color,
        fillOpacity: zone.status === "completed" ? 0.15 : 0.06,
        weight: zone.selected ? 3 : 2,
        dashArray: zone.status === "scanning" ? undefined : "6 4",
      };

      if (existing) {
        existing.setStyle(style);
      } else {
        if (zone.polygon.length < 3) return;
        const poly = L.polygon(zone.polygon, style).addTo(map);
        poly.bindTooltip(zone.label, { permanent: true, direction: "center", className: "zone-label-tooltip" });

        // Click to select
        poly.on("click", (e: L.LeafletMouseEvent) => {
          L.DomEvent.stopPropagation(e.originalEvent);
          const additive = e.originalEvent.shiftKey || e.originalEvent.ctrlKey || e.originalEvent.metaKey;
          selectZone(zone.zone_id, additive);
        });

        // Right-click context menu
        poly.on("contextmenu", (e: L.LeafletMouseEvent) => {
          L.DomEvent.preventDefault(e.originalEvent);
          L.DomEvent.stopPropagation(e.originalEvent);

          contextMenuRef.current?.remove();

          const selectedIds = state.selectedZoneIds.includes(zone.zone_id)
            ? state.selectedZoneIds
            : [zone.zone_id];

          const menuHtml = `
            <div style="display:flex;flex-direction:column;gap:4px;min-width:120px;">
              <div style="font-size:11px;font-weight:700;color:#aaa;margin-bottom:2px;">${selectedIds.length > 1 ? selectedIds.length + " zones" : zone.label}</div>
              <button class="zone-ctx-scan" style="background:none;border:1px solid #44ff88;color:#44ff88;padding:4px 8px;border-radius:3px;cursor:pointer;font-size:11px;">Scan</button>
              <button class="zone-ctx-stop" style="background:none;border:1px solid #ffaa44;color:#ffaa44;padding:4px 8px;border-radius:3px;cursor:pointer;font-size:11px;">Stop scan</button>
              <button class="zone-ctx-remove" style="background:none;border:1px solid #ff4444;color:#ff4444;padding:4px 8px;border-radius:3px;cursor:pointer;font-size:11px;">Remove</button>
            </div>
          `;

          const popup = L.popup({ closeButton: true, className: "zone-context-menu" })
            .setLatLng(e.latlng)
            .setContent(menuHtml)
            .openOn(map);

          contextMenuRef.current = popup;

          // Attach handlers after popup is added to DOM
          setTimeout(() => {
            const container = popup.getElement();
            if (!container) return;
            container.querySelector(".zone-ctx-scan")?.addEventListener("click", () => {
              scanZones(selectedIds);
              popup.remove();
            });
            container.querySelector(".zone-ctx-stop")?.addEventListener("click", () => {
              stopScanning(selectedIds);
              popup.remove();
            });
            container.querySelector(".zone-ctx-remove")?.addEventListener("click", () => {
              selectedIds.forEach((id) => removeZone(id));
              popup.remove();
            });
          }, 0);
        });

        layersRef.current[zone.zone_id] = poly;
      }
    });

    // Remove layers for zones that no longer exist
    Object.keys(layersRef.current).forEach((id) => {
      if (!seen.has(id)) {
        layersRef.current[id]?.remove();
        delete layersRef.current[id];
      }
    });
  }, [map, state.zones, state.selectedZoneIds]);

  // Render pending zones (pre-start, stored locally)
  useEffect(() => {
    // Remove old pending layers
    pendingLayersRef.current.forEach((l) => l.remove());
    pendingLayersRef.current = [];

    state.pendingZones.forEach((z, i) => {
      if (z.points.length < 3) return;
      const poly = L.polygon(z.points, {
        color: z.color,
        fillColor: z.color,
        fillOpacity: 0.08,
        weight: 2,
        dashArray: "4 4",
      }).addTo(map);
      const label = `Zone ${String.fromCharCode(65 + i)} (pending)`;
      poly.bindTooltip(label, { permanent: true, direction: "center", className: "zone-label-tooltip" });
      poly.on("contextmenu", (e: L.LeafletMouseEvent) => {
        L.DomEvent.preventDefault(e.originalEvent);
        removePendingZone(i);
      });
      pendingLayersRef.current.push(poly);
    });
  }, [map, state.pendingZones, removePendingZone]);

  // Click on empty map to deselect
  useEffect(() => {
    const handler = () => {
      if (state.selectedZoneIds.length > 0) {
        clearZoneSelection();
      }
    };
    map.on("click", handler);
    return () => { map.off("click", handler); };
  }, [map, state.selectedZoneIds.length, clearZoneSelection]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      Object.values(layersRef.current).forEach((l) => l.remove());
      layersRef.current = {};
      pendingLayersRef.current.forEach((l) => l.remove());
      pendingLayersRef.current = [];
      contextMenuRef.current?.remove();
    };
  }, [map]);

  return null;
}
