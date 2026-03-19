/**
 * MapView — Leaflet map. Lives for the full session.
 *
 * Map click behaviour is driven by context state — one place, no scattered conditionals:
 *   isPlacingSimBase     → click places base marker
 *   isDrawingSimBoundary → click+drag draws rectangle
 *   isDrawingZone        → click adds zone polygon vertex
 *   otherwise            → click disabled
 */

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  useMissionContext,
  isPlacingSimBase,
  isDrawingSimBoundary,
  isDrawingZone,
} from "../../context/MissionContext";
import { useMapRef } from "../../context/MapRefContext";
import type { LatLonTuple, SurvivorState } from "../../types/mission";
import { MasterPolygonLayer } from "./MasterPolygonLayer";
import { ZonePolygonLayer } from "./ZonePolygonLayer";
import { DroneMarkerLayer } from "./DroneMarkerLayer";
import { SurvivorMarkerLayer } from "./SurvivorMarkerLayer";
import { BaseMarker } from "./BaseMarker";
import { CoverageCanvas } from "./CoverageCanvas";

const CENTER: L.LatLngExpression = [3.314, 117.591];
const DEFAULT_ZOOM = 15;

export function MapView() {
  const { state, simSetBase, setDrawingZonePoly, simSetBoundary } = useMissionContext();
  const { setMap, panTo } = useMapRef();
  const { snapshot, mapDef, drawingZonePoly: zonePoly, simConfig } = state;

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const vertexMarkersRef = useRef<L.Marker[]>([]);
  const previewPolyRef = useRef<L.Polygon | null>(null);
  const simBaseMarkerRef = useRef<L.Marker | null>(null);
  const rectPreviewRef = useRef<L.Rectangle | null>(null);
  const rectStartRef = useRef<L.LatLng | null>(null);
  const isDraggingRef = useRef(false);

  // ── Init map once ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      zoomControl: true,
      scrollWheelZoom: true,
      doubleClickZoom: false,
    }).setView(CENTER, DEFAULT_ZOOM);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(map);

    mapRef.current = map;
    setMap(map);   // D1: register with MapRefContext

    // D4: GPS auto-locate
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          map.panTo([pos.coords.latitude, pos.coords.longitude]);
        },
        () => { /* silently fall back to Tarakan default */ }
      );
    }

    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // ── Sim base marker sync + D3: pan to base ────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    simBaseMarkerRef.current?.remove();
    if (!simConfig.base) return;
    simBaseMarkerRef.current = L.marker(simConfig.base, {
      icon: L.divIcon({
        className: "",
        html: `<div style="width:20px;height:20px;border-radius:50%;background:#ffaa44;border:2px solid #fff;display:flex;align-items:center;justify-content:center;font-size:9px;color:#050a0f;font-weight:700;box-shadow:0 0 8px rgba(255,170,68,.6)">B</div>`,
        iconSize: [20, 20], iconAnchor: [10, 10],
      }),
    }).addTo(map).bindTooltip("Sim Base", { permanent: false, direction: "top" });

    // D3: pan map to sim base so it becomes the visual centre
    panTo(simConfig.base[0], simConfig.base[1]);
  }, [simConfig.base, panTo]);

  // ── Interaction layer ──────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const placingBase = isPlacingSimBase(state);
    const drawingBoundary = isDrawingSimBoundary(state);
    const drawingZone = isDrawingZone(state);

    // Clear all previous handlers
    map.off("click");
    map.off("contextmenu");
    map.off("mousedown");
    map.off("mousemove");
    map.off("mouseup");
    map.dragging.enable();

    // ── Place sim base ───────────────────────────────────────────────────────
    if (placingBase) {
      map.getContainer().style.cursor = "crosshair";
      map.on("click", (e: L.LeafletMouseEvent) => {
        simSetBase([e.latlng.lat, e.latlng.lng]);
      });
      return () => { map.off("click"); map.getContainer().style.cursor = ""; };
    }

    // ── Draw sim boundary rectangle ──────────────────────────────────────────
    if (drawingBoundary) {
      map.getContainer().style.cursor = "crosshair";
      map.dragging.disable();

      map.on("mousedown", (e: L.LeafletMouseEvent) => {
        rectStartRef.current = e.latlng;
        isDraggingRef.current = true;
        rectPreviewRef.current?.remove();
        rectPreviewRef.current = null;
      });

      map.on("mousemove", (e: L.LeafletMouseEvent) => {
        if (!isDraggingRef.current || !rectStartRef.current) return;
        rectPreviewRef.current?.remove();
        const bounds = L.latLngBounds(rectStartRef.current, e.latlng);
        rectPreviewRef.current = L.rectangle(
          bounds,
          { color: "#ffaa44", fillColor: "#ffaa44", fillOpacity: 0.1, weight: 2, dashArray: "6 4" }
        ).addTo(map!);
      });

      map.on("mouseup", (e: L.LeafletMouseEvent) => {
        if (!isDraggingRef.current || !rectStartRef.current) return;
        isDraggingRef.current = false;
        const start = rectStartRef.current;
        const end = e.latlng;
        const rect: LatLonTuple[] = [
          [start.lat, start.lng],
          [start.lat, end.lng],
          [end.lat, end.lng],
          [end.lat, start.lng],
        ];
        simSetBoundary(rect);
        rectPreviewRef.current?.remove();
        rectPreviewRef.current = null;
        rectStartRef.current = null;
      });

      return () => {
        map.off("mousedown"); map.off("mousemove"); map.off("mouseup");
        map.dragging.enable();
        map.getContainer().style.cursor = "";
        rectPreviewRef.current?.remove();
        rectPreviewRef.current = null;
      };
    }

    // ── Draw zone polygon ────────────────────────────────────────────────────
    if (drawingZone) {
      map.getContainer().style.cursor = "crosshair";

      function clearVertices() {
        vertexMarkersRef.current.forEach((m) => m.remove());
        vertexMarkersRef.current = [];
      }

      function rebuildPreview(points: LatLonTuple[]) {
        previewPolyRef.current?.remove();
        if (points.length < 2) return;
        previewPolyRef.current = L.polygon(points, {
          color: "#44ff88", fillColor: "#44ff88",
          fillOpacity: 0.08, weight: 2, dashArray: "6 4",
        }).addTo(map!);
      }

      function addVertex(point: LatLonTuple, idx: number, current: LatLonTuple[]) {
        const m = L.marker(point, {
          draggable: true,
          icon: L.divIcon({
            className: "",
            html: `<div style="width:12px;height:12px;border-radius:50%;background:#44ff88;border:2px solid #fff;box-shadow:0 0 6px rgba(0,0,0,.5)"></div>`,
            iconSize: [12, 12], iconAnchor: [6, 6],
          }),
        }).addTo(map!);
        m.on("drag", (e) => {
          const ll = (e.target as L.Marker).getLatLng();
          const updated = [...current];
          updated[idx] = [ll.lat, ll.lng];
          setDrawingZonePoly(updated);
          rebuildPreview(updated);
        });
        vertexMarkersRef.current.push(m);
      }

      // Restore existing points
      clearVertices();
      rebuildPreview(zonePoly);
      zonePoly.forEach((p, i) => addVertex(p, i, zonePoly));

      map.on("click", (e: L.LeafletMouseEvent) => {
        const updated = [...zonePoly, [e.latlng.lat, e.latlng.lng] as LatLonTuple];
        setDrawingZonePoly(updated);
        rebuildPreview(updated);
        addVertex([e.latlng.lat, e.latlng.lng], updated.length - 1, updated);
      });

      map.on("contextmenu", () => {
        setDrawingZonePoly([]);
        clearVertices();
        previewPolyRef.current?.remove();
        previewPolyRef.current = null;
      });

      return () => {
        map.off("click"); map.off("contextmenu");
        clearVertices();
        previewPolyRef.current?.remove();
        previewPolyRef.current = null;
        map.getContainer().style.cursor = "";
      };
    }

    // No interaction mode
    map.getContainer().style.cursor = "";
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    state.simulationMode,
    state.simSetupStep,
    state.phase,
    zonePoly.length,
  ]);

  // ── Derive survivor source ─────────────────────────────────────────────────
  // Show survivors from tick snapshot when available.
  // Fall back to mapDef.survivors so they appear immediately after define_map.
  const survivorSource: Record<string, SurvivorState> =
    snapshot?.survivors ??
    Object.fromEntries(
      (mapDef?.survivors ?? []).map((s) => [
        s.id,
        { col: 0, row: 0, lat: s.lat, lon: s.lon, status: s.status as "missing" | "found" },
      ])
    );

  // ── Derive base position ───────────────────────────────────────────────────
  // Real mode: use mapDef.base. Sim mode: use simConfig.base (already shown via simBaseMarkerRef).
  const baseLatLon = mapDef?.base ?? null;

  // ── Drawing hint text ──────────────────────────────────────────────────────
  function hintText(): string | null {
    if (isPlacingSimBase(state)) return "Click to place drone base";
    if (isDrawingSimBoundary(state)) return "Click and drag to draw spawn rectangle · or click 'Use Full Map Canvas'";
    if (isDrawingZone(state)) return "Click to add zone points · Right-click to clear · Click zone to select · Shift+click for multi-select";
    return null;
  }

  const hint = hintText();

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />

      {mapRef.current && (
        <>
          {state.simConfig.boundaryRect && (
            <MasterPolygonLayer map={mapRef.current} points={state.simConfig.boundaryRect} color="#ffaa44" />
          )}
          <ZonePolygonLayer map={mapRef.current} />
          {baseLatLon && !state.simulationMode && (
            <BaseMarker map={mapRef.current} lat={baseLatLon.lat} lon={baseLatLon.lon} />
          )}
          {snapshot && (
            <>
              <DroneMarkerLayer map={mapRef.current} drones={snapshot.drones} />
              <CoverageCanvas map={mapRef.current} snapshot={snapshot} />
            </>
          )}
          <SurvivorMarkerLayer map={mapRef.current} survivors={survivorSource} />
        </>
      )}

      {hint && (
        <div style={{
          position: "absolute", bottom: 16, left: "50%", transform: "translateX(-50%)",
          background: "rgba(10,20,35,0.9)",
          border: `1px solid ${isDrawingZone(state) ? "rgba(68,255,136,0.3)" : "rgba(255,170,68,0.3)"}`,
          borderRadius: 4, padding: "6px 14px",
          fontSize: "0.73rem",
          color: isDrawingZone(state) ? "#44ff88" : "#ffaa44",
          pointerEvents: "none", zIndex: 1000, whiteSpace: "nowrap",
        }}>
          {hint}
        </div>
      )}
    </div>
  );
}
