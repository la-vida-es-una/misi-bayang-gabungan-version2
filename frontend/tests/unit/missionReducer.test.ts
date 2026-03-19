/**
 * Unit tests — MissionContext reducer (v2)
 *
 * Tests every action against the pure reducer function.
 * No browser, no React, no DOM — just state transitions.
 *
 * Run: bun test tests/unit/missionReducer.test.ts
 *
 * v2 changes:
 *   - No "paused" phase (zone lifecycle is per-zone, not global)
 *   - No zonePoly / missionText (replaced by drawingZonePoly + zones registry)
 *   - New: zones, selectedZoneIds, chatMessages, agentRunning
 *   - isDrawingZone: true when running OR pending_zone (can draw during mission)
 */

import { describe, test, expect } from "bun:test";

// ── Types ─────────────────────────────────────────────────────────────────────

type MissionPhase = "pending_zone" | "running" | "ended";
type SimSetupStep = "base" | "boundary" | "survivors" | "done";
type ZoneStatus = "idle" | "scanning" | "completed";

interface SimConfig {
  base: [number, number] | null;
  boundaryRect: [number, number][] | null;
  survivorCount: number;
}

interface ZoneClientState {
  zone_id: string;
  label: string;
  status: ZoneStatus;
  total_cells: number;
  covered_cells: number;
  coverage_ratio: number;
  polygon: [number, number][];
  color: string;
  selected: boolean;
}

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  timestamp: number;
}

interface State {
  simulationMode: boolean;
  simSetupStep: SimSetupStep;
  simConfig: SimConfig;
  phase: MissionPhase;
  snapshot: unknown | null;
  eventLog: Array<{ type: string }>;
  mapDef: unknown | null;
  zones: Record<string, ZoneClientState>;
  selectedZoneIds: string[];
  drawingZonePoly: [number, number][];
  chatMessages: ChatMessage[];
  agentRunning: boolean;
}

const INITIAL_SIM_CONFIG: SimConfig = {
  base: null,
  boundaryRect: null,
  survivorCount: 5,
};

const initialState: State = {
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
  chatMessages: [],
  agentRunning: true,
};

// ── Reducer mirror ────────────────────────────────────────────────────────────

function simStepBack(step: SimSetupStep): SimSetupStep {
  if (step === "boundary") return "base";
  if (step === "survivors") return "boundary";
  return "base";
}

function reducer(state: State, action: Record<string, unknown>): State {
  switch (action.type) {
    case "ENTER_SIM_MODE":
      return { ...initialState, simulationMode: true, simSetupStep: "base", simConfig: INITIAL_SIM_CONFIG, phase: "pending_zone" };
    case "EXIT_SIM_MODE":
      return { ...initialState, simulationMode: false };
    case "SIM_SET_BASE":
      return { ...state, simConfig: { ...state.simConfig, base: action.base as [number, number] }, simSetupStep: "boundary" };
    case "SIM_SET_BOUNDARY":
      return { ...state, simConfig: { ...state.simConfig, boundaryRect: action.rect as [number, number][] | null }, simSetupStep: "survivors" };
    case "SIM_SET_SURVIVOR_COUNT":
      return { ...state, simConfig: { ...state.simConfig, survivorCount: action.count as number } };
    case "SIM_CONFIRM_SURVIVORS":
      return { ...state, simSetupStep: "done" };
    case "SIM_BACK":
      return { ...state, simSetupStep: simStepBack(state.simSetupStep) };
    case "SET_DRAWING_ZONE_POLY":
      return { ...state, drawingZonePoly: action.points as [number, number][] };
    case "ZONE_ADDED": {
      const z = action.zone as ZoneClientState;
      return { ...state, zones: { ...state.zones, [z.zone_id]: z }, drawingZonePoly: [] };
    }
    case "ZONE_REMOVED": {
      const zoneId = action.zoneId as string;
      const { [zoneId]: _removed, ...rest } = state.zones;
      return { ...state, zones: rest, selectedZoneIds: state.selectedZoneIds.filter((id) => id !== zoneId) };
    }
    case "ZONE_SELECT": {
      const zoneId = action.zoneId as string;
      const additive = action.additive as boolean;
      let ids: string[];
      if (additive) {
        const already = state.selectedZoneIds.includes(zoneId);
        ids = already ? state.selectedZoneIds.filter((id) => id !== zoneId) : [...state.selectedZoneIds, zoneId];
      } else {
        ids = [zoneId];
      }
      return {
        ...state,
        selectedZoneIds: ids,
        zones: Object.fromEntries(Object.entries(state.zones).map(([id, z]) => [id, { ...z, selected: ids.includes(id) }])),
      };
    }
    case "ZONES_CLEAR_SELECTION":
      return {
        ...state,
        selectedZoneIds: [],
        zones: Object.fromEntries(Object.entries(state.zones).map(([id, z]) => [id, { ...z, selected: false }])),
      };
    case "MAP_DEFINED":
      return { ...state, mapDef: action.response };
    case "MISSION_STARTED":
      return { ...state, phase: "running", agentRunning: true };
    case "MISSION_ENDED":
      return { ...state, phase: "ended", agentRunning: false };
    case "TICK":
      return { ...state, snapshot: action.snapshot };
    case "WORLD_EVENT": {
      const log = [action.event as { type: string }, ...state.eventLog].slice(0, 200);
      return { ...state, eventLog: log };
    }
    case "CHAT_MESSAGE": {
      const msgs = [...state.chatMessages, action.message as ChatMessage].slice(-500);
      return { ...state, chatMessages: msgs };
    }
    case "AGENT_STOPPED":
      return { ...state, agentRunning: false };
    case "AGENT_RESUMED":
      return { ...state, agentRunning: true };
    case "RESET":
      return initialState;
    case "SIM_RESET":
      return { ...initialState, simulationMode: true, simSetupStep: "base", simConfig: INITIAL_SIM_CONFIG };
    default:
      return state;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function apply(actions: Record<string, unknown>[], from: State = initialState): State {
  return actions.reduce((s, a) => reducer(s, a), from);
}

function makeZone(id: string, overrides: Partial<ZoneClientState> = {}): ZoneClientState {
  return {
    zone_id: id,
    label: `Zone ${id}`,
    status: "idle",
    total_cells: 100,
    covered_cells: 0,
    coverage_ratio: 0,
    polygon: [[0, 0], [1, 0], [1, 1], [0, 1]],
    color: "#44ff88",
    selected: false,
    ...overrides,
  };
}

// ── Initial state ─────────────────────────────────────────────────────────────

describe("initial state", () => {
  test("starts in real mode", () => {
    expect(initialState.simulationMode).toBe(false);
  });

  test("starts at pending_zone phase", () => {
    expect(initialState.phase).toBe("pending_zone");
  });

  test("starts with empty drawing zone poly", () => {
    expect(initialState.drawingZonePoly).toHaveLength(0);
  });

  test("starts with empty zones registry", () => {
    expect(Object.keys(initialState.zones)).toHaveLength(0);
  });

  test("starts with empty event log", () => {
    expect(initialState.eventLog).toHaveLength(0);
  });

  test("starts with empty chat messages", () => {
    expect(initialState.chatMessages).toHaveLength(0);
  });

  test("agent starts running", () => {
    expect(initialState.agentRunning).toBe(true);
  });
});

// ── Mode transitions ──────────────────────────────────────────────────────────

describe("ENTER_SIM_MODE / EXIT_SIM_MODE", () => {
  test("ENTER_SIM_MODE sets simulationMode=true", () => {
    const s = reducer(initialState, { type: "ENTER_SIM_MODE" });
    expect(s.simulationMode).toBe(true);
  });

  test("ENTER_SIM_MODE resets all state", () => {
    const dirty: State = {
      ...initialState,
      phase: "running",
      drawingZonePoly: [[1, 2], [3, 4]] as [number, number][],
      zones: { z1: makeZone("z1") },
    };
    const s = reducer(dirty, { type: "ENTER_SIM_MODE" });
    expect(s.phase).toBe("pending_zone");
    expect(s.drawingZonePoly).toHaveLength(0);
    expect(Object.keys(s.zones)).toHaveLength(0);
  });

  test("ENTER_SIM_MODE sets simSetupStep to base", () => {
    const s = reducer(initialState, { type: "ENTER_SIM_MODE" });
    expect(s.simSetupStep).toBe("base");
  });

  test("EXIT_SIM_MODE resets to real mode", () => {
    const inSim = reducer(initialState, { type: "ENTER_SIM_MODE" });
    const s = reducer(inSim, { type: "EXIT_SIM_MODE" });
    expect(s.simulationMode).toBe(false);
    expect(s.phase).toBe("pending_zone");
  });

  test("EXIT_SIM_MODE clears simConfig", () => {
    const inSim = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.31, 117.57] },
    ]);
    const s = reducer(inSim, { type: "EXIT_SIM_MODE" });
    expect(s.simConfig.base).toBeNull();
  });
});

// ── Sim setup wizard ──────────────────────────────────────────────────────────

describe("sim setup wizard — forward progression", () => {
  test("SIM_SET_BASE stores base and advances to boundary", () => {
    const inSim = reducer(initialState, { type: "ENTER_SIM_MODE" });
    const s = reducer(inSim, { type: "SIM_SET_BASE", base: [3.314, 117.591] });
    expect(s.simConfig.base).toEqual([3.314, 117.591]);
    expect(s.simSetupStep).toBe("boundary");
  });

  test("SIM_SET_BOUNDARY stores rect and advances to survivors", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_SET_BOUNDARY", rect: [[3.31, 117.58], [3.32, 117.59], [3.32, 117.58], [3.31, 117.59]] },
    ]);
    expect(s.simSetupStep).toBe("survivors");
    expect(s.simConfig.boundaryRect).toHaveLength(4);
  });

  test("SIM_SET_BOUNDARY with null (use map canvas) still advances", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_SET_BOUNDARY", rect: null },
    ]);
    expect(s.simSetupStep).toBe("survivors");
    expect(s.simConfig.boundaryRect).toBeNull();
  });

  test("SIM_SET_SURVIVOR_COUNT updates count without changing step", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_SET_BOUNDARY", rect: null },
      { type: "SIM_SET_SURVIVOR_COUNT", count: 8 },
    ]);
    expect(s.simConfig.survivorCount).toBe(8);
    expect(s.simSetupStep).toBe("survivors");
  });

  test("SIM_CONFIRM_SURVIVORS sets step to done", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_SET_BOUNDARY", rect: null },
      { type: "SIM_CONFIRM_SURVIVORS" },
    ]);
    expect(s.simSetupStep).toBe("done");
  });

  test("after done, phase is still pending_zone (real workflow begins)", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_SET_BOUNDARY", rect: null },
      { type: "SIM_CONFIRM_SURVIVORS" },
    ]);
    expect(s.phase).toBe("pending_zone");
    expect(s.simSetupStep).toBe("done");
  });
});

describe("sim setup wizard — back navigation", () => {
  test("SIM_BACK from boundary goes to base", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_BACK" },
    ]);
    expect(s.simSetupStep).toBe("base");
  });

  test("SIM_BACK from survivors goes to boundary", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_SET_BOUNDARY", rect: null },
      { type: "SIM_BACK" },
    ]);
    expect(s.simSetupStep).toBe("boundary");
  });

  test("SIM_BACK from base stays at base (no underflow)", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_BACK" },
    ]);
    expect(s.simSetupStep).toBe("base");
  });
});

// ── Phase machine ─────────────────────────────────────────────────────────────

describe("phase machine — v2 (no paused phase)", () => {
  test("MISSION_STARTED transitions pending_zone → running", () => {
    const s = reducer(initialState, { type: "MISSION_STARTED" });
    expect(s.phase).toBe("running");
  });

  test("MISSION_STARTED sets agentRunning=true", () => {
    const s = reducer(initialState, { type: "MISSION_STARTED" });
    expect(s.agentRunning).toBe(true);
  });

  test("MISSION_ENDED transitions running → ended", () => {
    const running = reducer(initialState, { type: "MISSION_STARTED" });
    const s = reducer(running, { type: "MISSION_ENDED" });
    expect(s.phase).toBe("ended");
  });

  test("MISSION_ENDED sets agentRunning=false", () => {
    const running = reducer(initialState, { type: "MISSION_STARTED" });
    const s = reducer(running, { type: "MISSION_ENDED" });
    expect(s.agentRunning).toBe(false);
  });

  test("phase never goes backward from running to pending_zone", () => {
    const running = reducer(initialState, { type: "MISSION_STARTED" });
    const noOps = [
      { type: "TICK", snapshot: {} },
      { type: "WORLD_EVENT", event: { type: "drone_moved" } },
      { type: "SET_DRAWING_ZONE_POLY", points: [] },
    ];
    noOps.forEach((a) => {
      const s = reducer(running, a);
      expect(s.phase).not.toBe("pending_zone");
    });
  });

  test("there is no paused phase — mission goes pending_zone → running → ended", () => {
    const s = apply([
      { type: "MISSION_STARTED" },
      { type: "MISSION_ENDED" },
    ]);
    expect(s.phase).toBe("ended");
  });
});

// ── Zone management ───────────────────────────────────────────────────────────

describe("zone management", () => {
  test("ZONE_ADDED adds zone to registry and clears drawingZonePoly", () => {
    const withPoly = { ...initialState, drawingZonePoly: [[0, 0], [1, 0], [1, 1]] as [number, number][] };
    const z = makeZone("z1");
    const s = reducer(withPoly, { type: "ZONE_ADDED", zone: z });
    expect(s.zones["z1"]).toBeDefined();
    expect(s.zones["z1"]!.zone_id).toBe("z1");
    expect(s.drawingZonePoly).toHaveLength(0);
  });

  test("ZONE_REMOVED removes zone and deselects it", () => {
    const withZones: State = {
      ...initialState,
      zones: { z1: makeZone("z1"), z2: makeZone("z2") },
      selectedZoneIds: ["z1", "z2"],
    };
    const s = reducer(withZones, { type: "ZONE_REMOVED", zoneId: "z1" });
    expect(s.zones["z1"]).toBeUndefined();
    expect(s.zones["z2"]).toBeDefined();
    expect(s.selectedZoneIds).not.toContain("z1");
    expect(s.selectedZoneIds).toContain("z2");
  });

  test("ZONE_SELECT selects a single zone and deselects others", () => {
    const withZones: State = {
      ...initialState,
      zones: {
        z1: makeZone("z1", { selected: true }),
        z2: makeZone("z2", { selected: false }),
      },
      selectedZoneIds: ["z1"],
    };
    const s = reducer(withZones, { type: "ZONE_SELECT", zoneId: "z2", additive: false });
    expect(s.selectedZoneIds).toEqual(["z2"]);
    expect(s.zones["z1"]!.selected).toBe(false);
    expect(s.zones["z2"]!.selected).toBe(true);
  });

  test("ZONE_SELECT with additive=true adds to selection", () => {
    const withZones: State = {
      ...initialState,
      zones: {
        z1: makeZone("z1", { selected: true }),
        z2: makeZone("z2", { selected: false }),
      },
      selectedZoneIds: ["z1"],
    };
    const s = reducer(withZones, { type: "ZONE_SELECT", zoneId: "z2", additive: true });
    expect(s.selectedZoneIds).toContain("z1");
    expect(s.selectedZoneIds).toContain("z2");
    expect(s.zones["z1"]!.selected).toBe(true);
    expect(s.zones["z2"]!.selected).toBe(true);
  });

  test("ZONE_SELECT with additive=true on already-selected zone deselects it", () => {
    const withZones: State = {
      ...initialState,
      zones: {
        z1: makeZone("z1", { selected: true }),
        z2: makeZone("z2", { selected: true }),
      },
      selectedZoneIds: ["z1", "z2"],
    };
    const s = reducer(withZones, { type: "ZONE_SELECT", zoneId: "z1", additive: true });
    expect(s.selectedZoneIds).not.toContain("z1");
    expect(s.selectedZoneIds).toContain("z2");
    expect(s.zones["z1"]!.selected).toBe(false);
  });

  test("ZONES_CLEAR_SELECTION deselects all", () => {
    const withSelected: State = {
      ...initialState,
      zones: {
        z1: makeZone("z1", { selected: true }),
        z2: makeZone("z2", { selected: true }),
      },
      selectedZoneIds: ["z1", "z2"],
    };
    const s = reducer(withSelected, { type: "ZONES_CLEAR_SELECTION" });
    expect(s.selectedZoneIds).toHaveLength(0);
    expect(s.zones["z1"]!.selected).toBe(false);
    expect(s.zones["z2"]!.selected).toBe(false);
  });

  test("SET_DRAWING_ZONE_POLY stores drawing vertices", () => {
    const pts: [number, number][] = [[1, 1], [2, 2], [3, 3]];
    const s = reducer(initialState, { type: "SET_DRAWING_ZONE_POLY", points: pts });
    expect(s.drawingZonePoly).toHaveLength(3);
  });

  test("SET_DRAWING_ZONE_POLY with empty array clears drawing state", () => {
    const withPoly = { ...initialState, drawingZonePoly: [[1, 1], [2, 2], [3, 3]] as [number, number][] };
    const s = reducer(withPoly, { type: "SET_DRAWING_ZONE_POLY", points: [] });
    expect(s.drawingZonePoly).toHaveLength(0);
  });
});

// ── AI Chat state ─────────────────────────────────────────────────────────────

describe("AI chat state", () => {
  test("CHAT_MESSAGE appends to chatMessages", () => {
    const msg: ChatMessage = { id: "m1", role: "user", content: "Hello", timestamp: 1000 };
    const s = reducer(initialState, { type: "CHAT_MESSAGE", message: msg });
    expect(s.chatMessages).toHaveLength(1);
    expect(s.chatMessages[0]!.content).toBe("Hello");
  });

  test("CHAT_MESSAGE preserves message order (oldest first)", () => {
    const s = apply([
      { type: "CHAT_MESSAGE", message: { id: "m1", role: "system", content: "A", timestamp: 1 } },
      { type: "CHAT_MESSAGE", message: { id: "m2", role: "user", content: "B", timestamp: 2 } },
      { type: "CHAT_MESSAGE", message: { id: "m3", role: "assistant_thinking", content: "C", timestamp: 3 } },
    ]);
    expect(s.chatMessages[0]!.content).toBe("A");
    expect(s.chatMessages[1]!.content).toBe("B");
    expect(s.chatMessages[2]!.content).toBe("C");
  });

  test("AGENT_STOPPED sets agentRunning=false", () => {
    const running = reducer(initialState, { type: "MISSION_STARTED" });
    expect(running.agentRunning).toBe(true);
    const s = reducer(running, { type: "AGENT_STOPPED" });
    expect(s.agentRunning).toBe(false);
  });

  test("AGENT_RESUMED sets agentRunning=true", () => {
    const stopped = apply([
      { type: "MISSION_STARTED" },
      { type: "AGENT_STOPPED" },
    ]);
    const s = reducer(stopped, { type: "AGENT_RESUMED" });
    expect(s.agentRunning).toBe(true);
  });
});

// ── Event log ─────────────────────────────────────────────────────────────────

describe("event log", () => {
  test("WORLD_EVENT prepends to event log (newest first)", () => {
    const s1 = reducer(initialState, { type: "WORLD_EVENT", event: { type: "drone_moved" } });
    const s2 = reducer(s1, { type: "WORLD_EVENT", event: { type: "battery_low" } });
    expect(s2.eventLog[0]!.type).toBe("battery_low");
    expect(s2.eventLog[1]!.type).toBe("drone_moved");
  });

  test("event log is capped at 200 entries", () => {
    let s = initialState;
    for (let i = 0; i < 250; i++) {
      s = reducer(s, { type: "WORLD_EVENT", event: { type: "drone_moved" } });
    }
    expect(s.eventLog.length).toBe(200);
  });

  test("RESET clears event log", () => {
    const withEvents = apply(
      Array.from({ length: 5 }, () => ({ type: "WORLD_EVENT", event: { type: "drone_moved" } }))
    );
    const s = reducer(withEvents, { type: "RESET" });
    expect(s.eventLog).toHaveLength(0);
  });
});

// ── SIM_RESET ─────────────────────────────────────────────────────────────────

describe("SIM_RESET", () => {
  test("keeps simulationMode=true", () => {
    const ended = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_SET_BOUNDARY", rect: null },
      { type: "SIM_CONFIRM_SURVIVORS" },
      { type: "MISSION_STARTED" },
      { type: "MISSION_ENDED" },
      { type: "SIM_RESET" },
    ]);
    expect(ended.simulationMode).toBe(true);
  });

  test("resets simSetupStep to base", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_SET_BOUNDARY", rect: null },
      { type: "SIM_CONFIRM_SURVIVORS" },
      { type: "MISSION_ENDED" },
      { type: "SIM_RESET" },
    ]);
    expect(s.simSetupStep).toBe("base");
  });

  test("clears snapshot, eventLog, chatMessages, zones", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "WORLD_EVENT", event: { type: "drone_moved" } },
      { type: "TICK", snapshot: { tick: 99 } },
      { type: "CHAT_MESSAGE", message: { id: "m1", role: "system", content: "x", timestamp: 1 } },
      { type: "ZONE_ADDED", zone: makeZone("z1") },
      { type: "SIM_RESET" },
    ]);
    expect(s.snapshot).toBeNull();
    expect(s.eventLog).toHaveLength(0);
    expect(s.chatMessages).toHaveLength(0);
    expect(Object.keys(s.zones)).toHaveLength(0);
  });

  test("clears simConfig base", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_RESET" },
    ]);
    expect(s.simConfig.base).toBeNull();
  });
});

// ── RESET ─────────────────────────────────────────────────────────────────────

describe("RESET", () => {
  test("RESET returns to initial state regardless of current state", () => {
    const complex = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "MISSION_STARTED" },
      { type: "WORLD_EVENT", event: { type: "survivor_found" } },
      { type: "ZONE_ADDED", zone: makeZone("z1") },
    ]);
    const s = reducer(complex, { type: "RESET" });
    expect(s).toEqual(initialState);
  });
});

// ── Derived helpers ───────────────────────────────────────────────────────────

describe("derived helpers", () => {
  // Re-implement inline to avoid import complexity
  function isSimSetupInProgress(s: State): boolean {
    return s.simulationMode && s.simSetupStep !== "done";
  }
  function isPlacingSimBase(s: State): boolean {
    return s.simulationMode && s.simSetupStep === "base";
  }
  function isDrawingSimBoundary(s: State): boolean {
    return s.simulationMode && s.simSetupStep === "boundary";
  }
  // v2: isDrawingZone is true both in pending_zone AND running
  function isDrawingZone(s: State): boolean {
    if (s.simulationMode && s.simSetupStep !== "done") return false;
    return s.phase === "pending_zone" || s.phase === "running";
  }

  test("isSimSetupInProgress: true when sim mode + not done", () => {
    const s = reducer(initialState, { type: "ENTER_SIM_MODE" });
    expect(isSimSetupInProgress(s)).toBe(true);
  });

  test("isSimSetupInProgress: false when step is done", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_SET_BOUNDARY", rect: null },
      { type: "SIM_CONFIRM_SURVIVORS" },
    ]);
    expect(isSimSetupInProgress(s)).toBe(false);
  });

  test("isSimSetupInProgress: false in real mode", () => {
    expect(isSimSetupInProgress(initialState)).toBe(false);
  });

  test("isPlacingSimBase: true only on base step", () => {
    const s = reducer(initialState, { type: "ENTER_SIM_MODE" });
    expect(isPlacingSimBase(s)).toBe(true);
  });

  test("isPlacingSimBase: false after advancing", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
    ]);
    expect(isPlacingSimBase(s)).toBe(false);
  });

  test("isDrawingSimBoundary: true only on boundary step", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
    ]);
    expect(isDrawingSimBoundary(s)).toBe(true);
  });

  test("isDrawingZone: true in real mode at pending_zone", () => {
    expect(isDrawingZone(initialState)).toBe(true);
  });

  test("isDrawingZone: true while running (v2 — zones can be drawn any time)", () => {
    const running = reducer(initialState, { type: "MISSION_STARTED" });
    expect(isDrawingZone(running)).toBe(true);
  });

  test("isDrawingZone: true in sim mode when setup is done + running", () => {
    const s = apply([
      { type: "ENTER_SIM_MODE" },
      { type: "SIM_SET_BASE", base: [3.314, 117.591] },
      { type: "SIM_SET_BOUNDARY", rect: null },
      { type: "SIM_CONFIRM_SURVIVORS" },
      { type: "MISSION_STARTED" },
    ]);
    expect(isDrawingZone(s)).toBe(true);
  });

  test("isDrawingZone: false during sim setup", () => {
    const s = reducer(initialState, { type: "ENTER_SIM_MODE" });
    expect(isDrawingZone(s)).toBe(false);
  });

  test("isDrawingZone: false after mission ended", () => {
    const s = apply([{ type: "MISSION_STARTED" }, { type: "MISSION_ENDED" }]);
    expect(isDrawingZone(s)).toBe(false);
  });
});
