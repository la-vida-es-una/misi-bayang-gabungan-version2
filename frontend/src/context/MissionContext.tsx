/**
 * MissionContext — single source of truth for mission state.
 *
 * Phase machine (both modes):
 *   pending_zone → running → ended
 *
 * No "paused" global phase — zone lifecycle is per-zone.
 */

import {
  createContext,
  useCallback,
  useContext,
  useReducer,
  type ReactNode,
} from "react";
import type {
  ChatMessage,
  DefineMapResponse,
  LatLonTuple,
  MissionPhase,
  WorldEvent,
  WorldSnapshot,
  ZoneClientState,
} from "../types/mission";

// ── Sim setup step ────────────────────────────────────────────────────────────

export type SimSetupStep = "base" | "boundary" | "survivors" | "done";

export interface SimConfig {
  base: LatLonTuple | null;
  boundaryRect: LatLonTuple[] | null;
  survivorCount: number;
}

const ZONE_COLORS = [
  "#44ff88", "#44aaff", "#ff44aa", "#ffaa44", "#aa44ff",
  "#44ffdd", "#ff6644", "#88ff44", "#4488ff", "#ff44ff",
];

// ── State ─────────────────────────────────────────────────────────────────────

interface MissionState {
  simulationMode: boolean;
  simSetupStep: SimSetupStep;
  simConfig: SimConfig;

  phase: MissionPhase;
  snapshot: WorldSnapshot | null;
  eventLog: WorldEvent[];
  mapDef: DefineMapResponse | null;

  zones: Record<string, ZoneClientState>;
  selectedZoneIds: string[];
  drawingZonePoly: LatLonTuple[];
  // Zones drawn before mission start — held locally, registered after define_map
  pendingZones: Array<{ points: LatLonTuple[]; color: string }>;
  // Zones drawn during running mission — held locally until explicit apply
  queuedZones: Array<{ points: LatLonTuple[]; color: string }>;

  chatMessages: ChatMessage[];
  agentRunning: boolean;

  // Visualization: drone movement traces
  droneTraces: Record<string, LatLonTuple[]>;
  // Visualization: scan waypoint positions per drone
  scanWaypoints: Record<string, LatLonTuple[]>;

  // Simulator panel visibility toggles
  showMissingSurvivors: boolean;
  showSpawnRect: boolean;
}

const INITIAL_SIM_CONFIG: SimConfig = {
  base: null,
  boundaryRect: null,
  survivorCount: 5,
};

const initialState: MissionState = {
  simulationMode: false,
  simSetupStep: "base",
  simConfig: INITIAL_SIM_CONFIG,

  phase: "pending_zone",
  snapshot: null,
  eventLog: [],
  mapDef: null,

  zones: {},
  selectedZoneIds: [],
  drawingZonePoly: [],
  pendingZones: [],
  queuedZones: [],

  chatMessages: [],
  agentRunning: true,

  droneTraces: {},
  scanWaypoints: {},

  showMissingSurvivors: true,
  showSpawnRect: true,
};

// ── Actions ───────────────────────────────────────────────────────────────────

type Action =
  | { type: "ENTER_SIM_MODE" }
  | { type: "EXIT_SIM_MODE" }
  | { type: "SIM_SET_BASE"; base: LatLonTuple }
  | { type: "SIM_SET_BOUNDARY"; rect: LatLonTuple[] | null }
  | { type: "SIM_SET_SURVIVOR_COUNT"; count: number }
  | { type: "SIM_CONFIRM_SURVIVORS" }
  | { type: "SIM_BACK" }
  | { type: "SET_DRAWING_ZONE_POLY"; points: LatLonTuple[] }
  | { type: "PENDING_ZONE_ADD"; points: LatLonTuple[]; color: string }
  | { type: "PENDING_ZONE_REMOVE"; index: number }
  | { type: "QUEUED_ZONE_ADD"; points: LatLonTuple[]; color: string }
  | { type: "QUEUED_ZONE_REMOVE"; index: number }
  | { type: "QUEUED_ZONES_CLEAR" }
  | { type: "ZONE_ADDED"; zone: ZoneClientState }
  | { type: "ZONE_REMOVED"; zoneId: string }
  | { type: "ZONE_SELECT"; zoneId: string; additive: boolean }
  | { type: "ZONE_DESELECT"; zoneId: string }
  | { type: "ZONES_CLEAR_SELECTION" }
  | { type: "ZONES_UPDATE_FROM_SNAPSHOT"; zones: Record<string, { status: string; coverage_ratio: number; covered_cells: number; total_cells: number }> }
  | { type: "MAP_DEFINED"; response: DefineMapResponse }
  | { type: "MISSION_STARTED" }
  | { type: "MISSION_ENDED" }
  | { type: "TICK"; snapshot: WorldSnapshot }
  | { type: "WORLD_EVENT"; event: WorldEvent }
  | { type: "CHAT_MESSAGE"; message: ChatMessage }
  | { type: "AGENT_STOPPED" }
  | { type: "AGENT_RESUMED" }
  | { type: "DRONE_TRACE_UPDATE"; droneId: string; pos: LatLonTuple }
  | { type: "SCAN_WAYPOINT_ADD"; droneId: string; pos: LatLonTuple }
  | { type: "TOGGLE_SHOW_MISSING_SURVIVORS" }
  | { type: "TOGGLE_SHOW_SPAWN_RECT" }
  | { type: "RESET" }
  | { type: "SIM_RESET" };

const MAX_EVENT_LOG = 200;
const MAX_CHAT_MESSAGES = 500;

function simStepBack(step: SimSetupStep): SimSetupStep {
  switch (step) {
    case "boundary": return "base";
    case "survivors": return "boundary";
    default: return "base";
  }
}

let _chatMsgCounter = 0;
export function nextChatMsgId(): string {
  return `msg_${++_chatMsgCounter}`;
}

function reducer(state: MissionState, action: Action): MissionState {
  switch (action.type) {
    case "ENTER_SIM_MODE":
      return { ...initialState, simulationMode: true, simSetupStep: "base", simConfig: INITIAL_SIM_CONFIG, phase: "pending_zone" };
    case "EXIT_SIM_MODE":
      return { ...initialState, simulationMode: false };

    case "SIM_SET_BASE":
      return { ...state, simConfig: { ...state.simConfig, base: action.base }, simSetupStep: "boundary" };
    case "SIM_SET_BOUNDARY":
      return { ...state, simConfig: { ...state.simConfig, boundaryRect: action.rect }, simSetupStep: "survivors" };
    case "SIM_SET_SURVIVOR_COUNT":
      return { ...state, simConfig: { ...state.simConfig, survivorCount: action.count } };
    case "SIM_CONFIRM_SURVIVORS":
      return { ...state, simSetupStep: "done" };
    case "SIM_BACK":
      return { ...state, simSetupStep: simStepBack(state.simSetupStep) };

    case "SET_DRAWING_ZONE_POLY":
      return { ...state, drawingZonePoly: action.points };

    case "PENDING_ZONE_ADD":
      return {
        ...state,
        drawingZonePoly: [],
        pendingZones: [...state.pendingZones, { points: action.points, color: action.color }],
      };

    case "PENDING_ZONE_REMOVE":
      return {
        ...state,
        pendingZones: state.pendingZones.filter((_, i) => i !== action.index),
      };

    case "QUEUED_ZONE_ADD":
      return {
        ...state,
        drawingZonePoly: [],
        queuedZones: [...state.queuedZones, { points: action.points, color: action.color }],
      };

    case "QUEUED_ZONE_REMOVE":
      return {
        ...state,
        queuedZones: state.queuedZones.filter((_, i) => i !== action.index),
      };

    case "QUEUED_ZONES_CLEAR":
      return {
        ...state,
        queuedZones: [],
      };

    case "ZONE_ADDED":
      return { ...state, zones: { ...state.zones, [action.zone.zone_id]: action.zone }, drawingZonePoly: [] };

    case "ZONE_REMOVED": {
      const { [action.zoneId]: _, ...rest } = state.zones;
      return { ...state, zones: rest, selectedZoneIds: state.selectedZoneIds.filter((id) => id !== action.zoneId) };
    }

    case "ZONE_SELECT": {
      let ids: string[];
      if (action.additive) {
        const already = state.selectedZoneIds.includes(action.zoneId);
        ids = already ? state.selectedZoneIds.filter((id) => id !== action.zoneId) : [...state.selectedZoneIds, action.zoneId];
      } else {
        ids = [action.zoneId];
      }
      return {
        ...state,
        selectedZoneIds: ids,
        zones: Object.fromEntries(Object.entries(state.zones).map(([id, z]) => [id, { ...z, selected: ids.includes(id) }])),
      };
    }

    case "ZONE_DESELECT": {
      const zone = state.zones[action.zoneId];
      return {
        ...state,
        selectedZoneIds: state.selectedZoneIds.filter((id) => id !== action.zoneId),
        zones: zone
          ? { ...state.zones, [action.zoneId]: { ...zone, selected: false } }
          : state.zones,
      };
    }

    case "ZONES_CLEAR_SELECTION":
      return {
        ...state,
        selectedZoneIds: [],
        zones: Object.fromEntries(Object.entries(state.zones).map(([id, z]) => [id, { ...z, selected: false }])),
      };

    case "ZONES_UPDATE_FROM_SNAPSHOT": {
      const updated = { ...state.zones };
      for (const [zid, info] of Object.entries(action.zones)) {
        if (updated[zid]) {
          updated[zid] = {
            ...updated[zid],
            status: info.status as ZoneClientState["status"],
            coverage_ratio: info.coverage_ratio,
            covered_cells: info.covered_cells,
            total_cells: info.total_cells,
          };
        }
      }
      return { ...state, zones: updated };
    }

    case "MAP_DEFINED":
      return { ...state, mapDef: action.response };
    case "MISSION_STARTED":
      return { ...state, phase: "running", agentRunning: true, showSpawnRect: false };
    case "MISSION_ENDED":
      return { ...state, phase: "ended", agentRunning: false };

    case "TICK":
      return { ...state, snapshot: action.snapshot };
    case "WORLD_EVENT": {
      const log = [action.event, ...state.eventLog].slice(0, MAX_EVENT_LOG);
      return { ...state, eventLog: log };
    }

    case "CHAT_MESSAGE": {
      const msgs = [...state.chatMessages, action.message].slice(-MAX_CHAT_MESSAGES);
      return { ...state, chatMessages: msgs };
    }
    case "AGENT_STOPPED":
      return { ...state, agentRunning: false };
    case "AGENT_RESUMED":
      return { ...state, agentRunning: true };

    case "DRONE_TRACE_UPDATE": {
      const MAX_TRACE = 500;
      const prev = state.droneTraces[action.droneId] ?? [];
      const updated = [...prev, action.pos].slice(-MAX_TRACE);
      return { ...state, droneTraces: { ...state.droneTraces, [action.droneId]: updated } };
    }

    case "SCAN_WAYPOINT_ADD": {
      const prev = state.scanWaypoints[action.droneId] ?? [];
      return { ...state, scanWaypoints: { ...state.scanWaypoints, [action.droneId]: [...prev, action.pos] } };
    }

    case "TOGGLE_SHOW_MISSING_SURVIVORS":
      return { ...state, showMissingSurvivors: !state.showMissingSurvivors };
    case "TOGGLE_SHOW_SPAWN_RECT":
      return { ...state, showSpawnRect: !state.showSpawnRect };

    case "RESET":
      return initialState;
    case "SIM_RESET":
      return { ...initialState, simulationMode: true, simSetupStep: "base", simConfig: INITIAL_SIM_CONFIG };

    default:
      return state;
  }
}

// ── Derived helpers ──────────────────────────────────────────────────────────

export function isSimSetupInProgress(state: MissionState): boolean {
  return state.simulationMode && state.simSetupStep !== "done";
}

export function isPlacingSimBase(state: MissionState): boolean {
  return state.simulationMode && state.simSetupStep === "base";
}

export function isDrawingSimBoundary(state: MissionState): boolean {
  return state.simulationMode && state.simSetupStep === "boundary";
}

export function isDrawingZone(state: MissionState): boolean {
  if (state.simulationMode && state.simSetupStep !== "done") return false;
  return state.phase === "pending_zone" || state.phase === "running";
}

export function getNextZoneColor(state: MissionState): string {
  const usedColors = Object.values(state.zones).map((z) => z.color);
  for (const c of ZONE_COLORS) {
    if (!usedColors.includes(c)) return c;
  }
  return ZONE_COLORS[Object.keys(state.zones).length % ZONE_COLORS.length] ?? "#44ff88";
}

// ── Context ───────────────────────────────────────────────────────────────────

interface MissionContextValue {
  state: MissionState;
  enterSimMode: () => void;
  exitSimMode: () => void;
  simSetBase: (base: LatLonTuple) => void;
  simSetBoundary: (rect: LatLonTuple[] | null) => void;
  simSetSurvivorCount: (count: number) => void;
  simConfirmSurvivors: () => void;
  simBack: () => void;
  setDrawingZonePoly: (points: LatLonTuple[]) => void;
  addPendingZone: (points: LatLonTuple[], color: string) => void;
  removePendingZone: (index: number) => void;
  addQueuedZone: (points: LatLonTuple[], color: string) => void;
  removeQueuedZone: (index: number) => void;
  clearQueuedZones: () => void;
  dispatchZoneAdded: (zone: ZoneClientState) => void;
  dispatchZoneRemoved: (zoneId: string) => void;
  selectZone: (zoneId: string, additive: boolean) => void;
  deselectZone: (zoneId: string) => void;
  clearZoneSelection: () => void;
  updateZonesFromSnapshot: (zones: Record<string, { status: string; coverage_ratio: number; covered_cells: number; total_cells: number }>) => void;
  dispatchMapDefined: (response: DefineMapResponse) => void;
  dispatchMissionStarted: () => void;
  dispatchMissionEnded: () => void;
  dispatchTick: (snapshot: WorldSnapshot) => void;
  dispatchWorldEvent: (event: WorldEvent) => void;
  addChatMessage: (message: ChatMessage) => void;
  dispatchAgentStopped: () => void;
  dispatchAgentResumed: () => void;
  dispatchDroneTraceUpdate: (droneId: string, pos: LatLonTuple) => void;
  dispatchScanWaypointAdd: (droneId: string, pos: LatLonTuple) => void;
  toggleShowMissingSurvivors: () => void;
  toggleShowSpawnRect: () => void;
  reset: () => void;
  simReset: () => void;
}

const MissionContext = createContext<MissionContextValue | null>(null);

export function MissionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const enterSimMode = useCallback(() => dispatch({ type: "ENTER_SIM_MODE" }), []);
  const exitSimMode = useCallback(() => dispatch({ type: "EXIT_SIM_MODE" }), []);
  const simSetBase = useCallback((base: LatLonTuple) => dispatch({ type: "SIM_SET_BASE", base }), []);
  const simSetBoundary = useCallback((rect: LatLonTuple[] | null) => dispatch({ type: "SIM_SET_BOUNDARY", rect }), []);
  const simSetSurvivorCount = useCallback((count: number) => dispatch({ type: "SIM_SET_SURVIVOR_COUNT", count }), []);
  const simConfirmSurvivors = useCallback(() => dispatch({ type: "SIM_CONFIRM_SURVIVORS" }), []);
  const simBack = useCallback(() => dispatch({ type: "SIM_BACK" }), []);
  const setDrawingZonePoly = useCallback((points: LatLonTuple[]) => dispatch({ type: "SET_DRAWING_ZONE_POLY", points }), []);
  const addPendingZone = useCallback((points: LatLonTuple[], color: string) => dispatch({ type: "PENDING_ZONE_ADD", points, color }), []);
  const removePendingZone = useCallback((index: number) => dispatch({ type: "PENDING_ZONE_REMOVE", index }), []);
  const addQueuedZone = useCallback((points: LatLonTuple[], color: string) => dispatch({ type: "QUEUED_ZONE_ADD", points, color }), []);
  const removeQueuedZone = useCallback((index: number) => dispatch({ type: "QUEUED_ZONE_REMOVE", index }), []);
  const clearQueuedZones = useCallback(() => dispatch({ type: "QUEUED_ZONES_CLEAR" }), []);
  const dispatchZoneAdded = useCallback((zone: ZoneClientState) => dispatch({ type: "ZONE_ADDED", zone }), []);
  const dispatchZoneRemoved = useCallback((zoneId: string) => dispatch({ type: "ZONE_REMOVED", zoneId }), []);
  const selectZone = useCallback((zoneId: string, additive: boolean) => dispatch({ type: "ZONE_SELECT", zoneId, additive }), []);
  const deselectZone = useCallback((zoneId: string) => dispatch({ type: "ZONE_DESELECT", zoneId }), []);
  const clearZoneSelection = useCallback(() => dispatch({ type: "ZONES_CLEAR_SELECTION" }), []);
  const updateZonesFromSnapshot = useCallback((zones: Record<string, { status: string; coverage_ratio: number; covered_cells: number; total_cells: number }>) => dispatch({ type: "ZONES_UPDATE_FROM_SNAPSHOT", zones }), []);
  const dispatchMapDefined = useCallback((response: DefineMapResponse) => dispatch({ type: "MAP_DEFINED", response }), []);
  const dispatchMissionStarted = useCallback(() => dispatch({ type: "MISSION_STARTED" }), []);
  const dispatchMissionEnded = useCallback(() => dispatch({ type: "MISSION_ENDED" }), []);
  const dispatchTick = useCallback((snapshot: WorldSnapshot) => dispatch({ type: "TICK", snapshot }), []);
  const dispatchWorldEvent = useCallback((event: WorldEvent) => dispatch({ type: "WORLD_EVENT", event }), []);
  const addChatMessage = useCallback((message: ChatMessage) => dispatch({ type: "CHAT_MESSAGE", message }), []);
  const dispatchAgentStopped = useCallback(() => dispatch({ type: "AGENT_STOPPED" }), []);
  const dispatchAgentResumed = useCallback(() => dispatch({ type: "AGENT_RESUMED" }), []);
  const dispatchDroneTraceUpdate = useCallback((droneId: string, pos: LatLonTuple) => dispatch({ type: "DRONE_TRACE_UPDATE", droneId, pos }), []);
  const dispatchScanWaypointAdd = useCallback((droneId: string, pos: LatLonTuple) => dispatch({ type: "SCAN_WAYPOINT_ADD", droneId, pos }), []);
  const toggleShowMissingSurvivors = useCallback(() => dispatch({ type: "TOGGLE_SHOW_MISSING_SURVIVORS" }), []);
  const toggleShowSpawnRect = useCallback(() => dispatch({ type: "TOGGLE_SHOW_SPAWN_RECT" }), []);
  const reset = useCallback(() => dispatch({ type: "RESET" }), []);
  const simReset = useCallback(() => dispatch({ type: "SIM_RESET" }), []);

  return (
    <MissionContext.Provider value={{
      state,
      enterSimMode, exitSimMode,
      simSetBase, simSetBoundary, simSetSurvivorCount, simConfirmSurvivors, simBack,
      setDrawingZonePoly, addPendingZone, removePendingZone,
      addQueuedZone, removeQueuedZone, clearQueuedZones,
      dispatchZoneAdded, dispatchZoneRemoved, selectZone, deselectZone, clearZoneSelection, updateZonesFromSnapshot,
      dispatchMapDefined, dispatchMissionStarted, dispatchMissionEnded,
      dispatchTick, dispatchWorldEvent,
      addChatMessage, dispatchAgentStopped, dispatchAgentResumed,
      dispatchDroneTraceUpdate, dispatchScanWaypointAdd,
      toggleShowMissingSurvivors, toggleShowSpawnRect,
      reset, simReset,
    }}>
      {children}
    </MissionContext.Provider>
  );
}

export function useMissionContext(): MissionContextValue {
  const ctx = useContext(MissionContext);
  if (!ctx) throw new Error("useMissionContext must be used inside MissionProvider");
  return ctx;
}
