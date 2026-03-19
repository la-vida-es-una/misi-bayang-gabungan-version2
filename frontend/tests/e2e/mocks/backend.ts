/**
 * Backend mock helpers.
 *
 * All /mission/* requests are intercepted by Playwright's route API.
 * SSE events are injected via page.evaluate() into a synthetic EventSource.
 *
 * Usage:
 *   import { mockBackend } from "../mocks/backend";
 *   const mock = await mockBackend(page);
 *   await mock.emitSSE({ event: "tick", data: TICK_SNAPSHOT });
 */

import type { Page, Route } from "@playwright/test";

// ── Canonical fake responses ──────────────────────────────────────────────────

export const DEFINE_MAP_RESPONSE = {
  mission_id: "test0001",
  grid_bounds: {
    cols: 20,
    rows: 20,
    cell_size_m: 1.0,
    master_cells: 400,
    zone_count: 0,
    zones: {},
    scanning_coverage_ratio: 0,
  },
  base: { col: 0, row: 0, lat: 3.314, lon: 117.591 },
  drone_ids: ["drone_1", "drone_2", "drone_3"],
  survivors: [
    { id: "s1", lat: 3.315, lon: 117.592, status: "missing" },
    { id: "s2", lat: 3.316, lon: 117.593, status: "missing" },
  ],
};

export const START_RESPONSE = {
  ok: true,
  phase: "running",
};

export const ADD_ZONE_RESPONSE = {
  ok: true,
  zone_id: "zone_abc123",
  zone: {
    zone_id: "zone_abc123",
    label: "Zone A",
    status: "idle",
    total_cells: 64,
    covered_cells: 0,
    coverage_ratio: 0,
  },
};

export const ZONE_REMOVE_RESPONSE = { ok: true, zone_id: "zone_abc123" };
export const ZONE_SCAN_RESPONSE = { ok: true, scanning: ["zone_abc123"] };
export const ZONE_STOP_RESPONSE = { ok: true, stopped: ["zone_abc123"] };
export const AGENT_STOP_RESPONSE = { ok: true, agent: "stopped" };
export const AGENT_RESUME_RESPONSE = { ok: true, agent: "resumed" };
export const AGENT_PROMPT_RESPONSE = { ok: true, message: "queued" };
export const END_RESPONSE = { ok: true, phase: "ended" };

export const TICK_SNAPSHOT = {
  tick: 42,
  phase: "running",
  grid: {
    cols: 20,
    rows: 20,
    cell_size_m: 1.0,
    master_cells: 400,
    zone_count: 1,
    zones: {
      zone_abc123: {
        zone_id: "zone_abc123",
        label: "Zone A",
        status: "scanning",
        total_cells: 64,
        covered_cells: 20,
        coverage_ratio: 0.3125,
      },
    },
    scanning_coverage_ratio: 0.3125,
  },
  base: { col: 0, row: 0 },
  drones: {
    drone_1: { col: 5, row: 3, lat: 3.3145, lon: 117.5915, battery: 82, status: "moving", path_remaining: 14 },
    drone_2: { col: 0, row: 0, lat: 3.3140, lon: 117.5910, battery: 23, status: "charging", path_remaining: 0 },
    drone_3: { col: 9, row: 4, lat: 3.3149, lon: 117.5919, battery: 61, status: "scanning", path_remaining: 7 },
  },
  survivors: {
    s1: { col: 4, row: 2, lat: 3.3144, lon: 117.5914, status: "missing" },
    s2: { col: 8, row: 6, lat: 3.3148, lon: 117.5918, status: "missing" },
  },
};

export const TICK_SURVIVOR_FOUND = {
  ...TICK_SNAPSHOT,
  tick: 43,
  survivors: {
    s1: { col: 4, row: 2, lat: 3.3144, lon: 117.5914, status: "found" },
    s2: { col: 8, row: 6, lat: 3.3148, lon: 117.5918, status: "missing" },
  },
};

export const TICK_ZONE_COVERED = {
  ...TICK_SNAPSHOT,
  tick: 200,
  grid: {
    ...TICK_SNAPSHOT.grid,
    zones: {
      zone_abc123: {
        zone_id: "zone_abc123",
        label: "Zone A",
        status: "completed",
        total_cells: 64,
        covered_cells: 64,
        coverage_ratio: 1.0,
      },
    },
    scanning_coverage_ratio: 1.0,
  },
  drones: {
    drone_1: { col: 0, row: 0, lat: 3.3140, lon: 117.5910, battery: 95, status: "idle", path_remaining: 0 },
    drone_2: { col: 0, row: 0, lat: 3.3140, lon: 117.5910, battery: 100, status: "idle", path_remaining: 0 },
    drone_3: { col: 0, row: 0, lat: 3.3140, lon: 117.5910, battery: 88, status: "idle", path_remaining: 0 },
  },
};

// ── SSE injection ─────────────────────────────────────────────────────────────
// We inject a synthetic EventSource into the page that we can feed from tests.

const SSE_SETUP_SCRIPT = `
  window.__sseQueue = [];
  window.__sseListeners = [];
  window.__sseUrls = [];
  window.__pushSSE = function(payload) {
    const ev = new MessageEvent('message', { data: JSON.stringify(payload) });
    window.__sseListeners.forEach(fn => fn(ev));
  };
  window.__OriginalEventSource = window.EventSource;
  window.EventSource = class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.readyState = 1;
      window.__sseUrls.push(url);
      window.__sseListeners = [];
    }
    set onmessage(fn) { window.__sseListeners.push(fn); }
    get onmessage()   { return window.__sseListeners[0] || null; }
    set onerror(_fn)  {}
    close()           { window.__sseListeners = []; this.readyState = 2; }
  };
`;

// ── Mock installer ────────────────────────────────────────────────────────────

export interface BackendMock {
  emitSSE: (payload: { event: string; data: unknown }) => Promise<void>;
  emitTick: (snapshot?: typeof TICK_SNAPSHOT) => Promise<void>;
  emitEvent: (type: string, data: unknown) => Promise<void>;
}

export async function mockBackend(page: Page): Promise<BackendMock> {
  // Inject fake EventSource before page scripts run
  await page.addInitScript(SSE_SETUP_SCRIPT);

  // Intercept all REST calls
  await page.route("**/mission/define_map", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(DEFINE_MAP_RESPONSE) })
  );
  await page.route("**/mission/start", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(START_RESPONSE) })
  );
  await page.route("**/mission/zone/add", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ADD_ZONE_RESPONSE) })
  );
  await page.route("**/mission/zone/remove", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ZONE_REMOVE_RESPONSE) })
  );
  await page.route("**/mission/zone/scan", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ZONE_SCAN_RESPONSE) })
  );
  await page.route("**/mission/zone/stop", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ZONE_STOP_RESPONSE) })
  );
  await page.route("**/mission/agent/stop", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(AGENT_STOP_RESPONSE) })
  );
  await page.route("**/mission/agent/resume", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(AGENT_RESUME_RESPONSE) })
  );
  await page.route("**/mission/agent/prompt", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(AGENT_PROMPT_RESPONSE) })
  );
  await page.route("**/mission/end", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(END_RESPONSE) })
  );
  await page.route("**/mission/stream", (r: Route) =>
    // SSE endpoint — return empty stream, we inject events manually
    r.fulfill({ status: 200, contentType: "text/event-stream", body: "" })
  );
  await page.route("**/health", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) })
  );

  return {
    emitSSE: (payload) =>
      page.evaluate((p) => (window as unknown as { __pushSSE: (p: unknown) => void }).__pushSSE(p), payload),

    emitTick: (snapshot = TICK_SNAPSHOT) =>
      page.evaluate(
        (s) => (window as unknown as { __pushSSE: (p: unknown) => void }).__pushSSE({ event: "tick", data: s }),
        snapshot,
      ),

    emitEvent: (type, data) =>
      page.evaluate(
        ({ t, d }: { t: string; d: unknown }) =>
          (window as unknown as { __pushSSE: (p: unknown) => void }).__pushSSE({ event: t, data: { ...(d as object), type: t } }),
        { t: type, d: data },
      ),
  };
}
