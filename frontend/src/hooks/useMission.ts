/**
 * useMission — all REST calls to the backend.
 *
 * Flow:
 *   1. define_map (auto, from sim config or map viewport)
 *   2. start (begins world ticks + agent, no zone required)
 *   3. zone/add, zone/remove, zone/scan, zone/stop (any time while running)
 *   4. agent/stop, agent/resume, agent/prompt
 *   5. end
 */

import { useCallback, useState } from "react";
import { useMissionContext, getNextZoneColor, nextChatMsgId } from "../context/MissionContext";
import { useMapRef } from "../context/MapRefContext";
import type {
  DefineMapRequest,
  DefineMapResponse,
  GeoJSONPolygon,
  LatLon,
  LatLonTuple,
  StartMissionRequest,
  StartMissionResponse,
  ZoneAddResponse,
  ZoneClientState,
} from "../types/mission";

const API = "";

// ── GeoJSON helper ────────────────────────────────────────────────────────────

export function toGeoJSON(points: LatLonTuple[]): GeoJSONPolygon {
  if (points.length === 0) return { type: "Polygon", coordinates: [[]] };
  const ring = [...points];
  const first = ring[0]!;
  const last = ring[ring.length - 1]!;
  if (first[0] !== last[0] || first[1] !== last[1]) {
    ring.push(first);
  }
  return { type: "Polygon", coordinates: [ring] };
}

// ── Fetch helpers ─────────────────────────────────────────────────────────────

async function post<T>(
  path: string,
  body: unknown
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  try {
    const res = await fetch(`${API}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, error: `HTTP ${res.status}: ${text}` };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useMission() {
  const {
    state,
    dispatchMapDefined,
    dispatchMissionStarted,
    dispatchMissionEnded,
    dispatchZoneAdded,
    dispatchZoneRemoved,
    addChatMessage,
    dispatchAgentStopped,
    dispatchAgentResumed,
  } = useMissionContext();

  const { getMapBounds, getMap } = useMapRef();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Internal: define_map ───────────────────────────────────────────────────

  async function _defineMap(
    boundary: LatLonTuple[],
    base: LatLon,
    droneIds: string[],
    survivorCount: number,
    cellSizeM: number,
  ): Promise<DefineMapResponse | null> {
    const body: DefineMapRequest = {
      geojson_polygon: toGeoJSON(boundary),
      drone_ids: droneIds,
      survivor_count: survivorCount,
      base,
      cell_size_m: cellSizeM,
    };
    const result = await post<DefineMapResponse>("/mission/define_map", body);
    if (!result.ok) return null;
    dispatchMapDefined(result.data);
    return result.data;
  }

  // ── startMission ──────────────────────────────────────────────────────────

  const startMission = useCallback(async (opts: {
    missionText?: string;
    droneCount?: number;
    cellSizeM?: number;
  } = {}) => {
    setLoading(true);
    setError(null);

    const droneCount = opts.droneCount ?? 3;
    const cellSizeM = opts.cellSizeM ?? 1.0;
    const missionText = opts.missionText ?? "Scan zones for survivors.";
    const droneIds = Array.from({ length: droneCount }, (_, i) => `drone_${i + 1}`);

    let boundary: LatLonTuple[] | null = null;
    let base: LatLon;

    if (state.simulationMode) {
      boundary = state.simConfig.boundaryRect ?? getMapBounds();
      if (!state.simConfig.base) {
        setError("Sim base location not set.");
        setLoading(false);
        return false;
      }
      base = { lat: state.simConfig.base[0], lon: state.simConfig.base[1] };
    } else {
      boundary = getMapBounds();
      const map = getMap();
      const centre = map?.getCenter();
      base = centre
        ? { lat: centre.lat, lon: centre.lng }
        : { lat: 3.314, lon: 117.591 };
    }

    if (!boundary) {
      setError("Map not ready -- cannot read bounds.");
      setLoading(false);
      return false;
    }

    // Step 1: define_map
    const mapDef = await _defineMap(
      boundary, base, droneIds,
      state.simulationMode ? state.simConfig.survivorCount : 0,
      cellSizeM,
    );
    if (!mapDef) {
      setError("Failed to define map -- check backend connection.");
      setLoading(false);
      return false;
    }

    // Step 2: start
    const body: StartMissionRequest = { mission_text: missionText };
    const result = await post<StartMissionResponse>("/mission/start", body);
    setLoading(false);

    if (!result.ok) {
      setError(result.error);
      return false;
    }

    dispatchMissionStarted();
    return true;
  }, [state.simulationMode, state.simConfig, getMapBounds, getMap, dispatchMissionStarted, dispatchMapDefined]);

  // ── addZone ───────────────────────────────────────────────────────────────

  const addZone = useCallback(async (zonePoly: LatLonTuple[], label?: string) => {
    setLoading(true);
    setError(null);
    const body = { geojson_polygon: toGeoJSON(zonePoly), label: label ?? null };
    const result = await post<ZoneAddResponse>("/mission/zone/add", body);
    setLoading(false);
    if (!result.ok) { setError(result.error); return null; }

    const zoneClient: ZoneClientState = {
      ...result.data.zone,
      polygon: zonePoly,
      color: getNextZoneColor(state),
      selected: false,
    };
    dispatchZoneAdded(zoneClient);
    return result.data.zone_id;
  }, [state, dispatchZoneAdded]);

  // ── removeZone ────────────────────────────────────────────────────────────

  const removeZone = useCallback(async (zoneId: string) => {
    const result = await post<{ ok: boolean }>("/mission/zone/remove", { zone_id: zoneId });
    if (!result.ok) { setError(result.error); return false; }
    dispatchZoneRemoved(zoneId);
    return true;
  }, [dispatchZoneRemoved]);

  // ── scanZones ─────────────────────────────────────────────────────────────

  const scanZones = useCallback(async (zoneIds: string[]) => {
    const result = await post<{ ok: boolean }>("/mission/zone/scan", { zone_ids: zoneIds });
    if (!result.ok) { setError(result.error); return false; }
    return true;
  }, []);

  // ── stopScanning ──────────────────────────────────────────────────────────

  const stopScanning = useCallback(async (zoneIds: string[]) => {
    const result = await post<{ ok: boolean }>("/mission/zone/stop", { zone_ids: zoneIds });
    if (!result.ok) { setError(result.error); return false; }
    return true;
  }, []);

  // ── stopAgent ─────────────────────────────────────────────────────────────

  const stopAgent = useCallback(async () => {
    const result = await post<{ ok: boolean }>("/mission/agent/stop", {});
    if (!result.ok) { setError(result.error); return false; }
    dispatchAgentStopped();
    return true;
  }, [dispatchAgentStopped]);

  // ── resumeAgent ───────────────────────────────────────────────────────────

  const resumeAgent = useCallback(async () => {
    const result = await post<{ ok: boolean }>("/mission/agent/resume", {});
    if (!result.ok) { setError(result.error); return false; }
    dispatchAgentResumed();
    return true;
  }, [dispatchAgentResumed]);

  // ── promptAgent ───────────────────────────────────────────────────────────

  const promptAgent = useCallback(async (message: string) => {
    // Add user message to chat immediately
    addChatMessage({
      id: nextChatMsgId(),
      role: "user",
      content: message,
      timestamp: Date.now(),
    });
    const result = await post<{ ok: boolean }>("/mission/agent/prompt", { message });
    if (!result.ok) { setError(result.error); return false; }
    return true;
  }, [addChatMessage]);

  // ── endMission ────────────────────────────────────────────────────────────

  const endMission = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await post<{ ok: boolean }>("/mission/end", {});
    setLoading(false);
    if (!result.ok) { setError(result.error); return false; }
    dispatchMissionEnded();
    return true;
  }, [dispatchMissionEnded]);

  return {
    loading, error,
    startMission, addZone, removeZone,
    scanZones, stopScanning,
    stopAgent, resumeAgent, promptAgent,
    endMission,
  };
}
