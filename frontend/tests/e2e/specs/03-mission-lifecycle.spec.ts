/**
 * 03 — Mission lifecycle validation
 *
 * Real mode flow:
 *   pending_zone → running → paused → running → ended
 *
 * startMission now triggers define_map + start internally.
 * All backend calls are mocked. SSE injected manually.
 */

import { test, expect } from "@playwright/test";
import {
  mockBackend,
  TICK_SNAPSHOT,
  DEFINE_MAP_RESPONSE,
  START_RESPONSE,
} from "../mocks/backend";

// ── Helpers ───────────────────────────────────────────────────────────────────

async function clickMap(page: import("@playwright/test").Page, x: number, y: number) {
  const box = await page.locator(".leaflet-container").boundingBox();
  await page.mouse.click(box!.x + x, box!.y + y);
  await page.waitForTimeout(80);
}

async function drawZone(page: import("@playwright/test").Page) {
  await clickMap(page, 100, 100);
  await clickMap(page, 250, 100);
  await clickMap(page, 250, 250);
  await clickMap(page, 100, 250);
}

async function launchMission(page: import("@playwright/test").Page) {
  await page.waitForSelector(".leaflet-container");
  await page.waitForTimeout(500);
  await drawZone(page);
  await page.locator("textarea").fill("Scan the area for survivors");
  await page.getByRole("button", { name: /launch mission/i }).click();
  await page.waitForTimeout(400);
}

// ── Tests: pending_zone → running ─────────────────────────────────────────────

test.describe("launch sequence", () => {
  test("launch calls define_map then start in sequence", async ({ page }) => {
    const calls: string[] = [];
    await mockBackend(page);

    await page.route("**/mission/define_map", async (route) => {
      calls.push("define_map");
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify(DEFINE_MAP_RESPONSE),
      });
    });
    await page.route("**/mission/start", async (route) => {
      calls.push("start");
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify(START_RESPONSE),
      });
    });

    await page.goto("/");
    await launchMission(page);

    expect(calls[0]).toBe("define_map");
    expect(calls[1]).toBe("start");
    expect(calls).toHaveLength(2);
  });

  test("define_map body contains geojson_polygon, drone_ids, base", async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null;
    await mockBackend(page);
    await page.route("**/mission/define_map", async (route) => {
      capturedBody = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify(DEFINE_MAP_RESPONSE),
      });
    });

    await page.goto("/");
    await launchMission(page);

    expect(capturedBody).not.toBeNull();
    expect((capturedBody!.geojson_polygon as any).type).toBe("Polygon");
    expect(Array.isArray(capturedBody!.drone_ids)).toBe(true);
    expect(capturedBody!.base).toBeDefined();
  });

  test("start body contains zone.geojson_polygon and mission_text", async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null;
    await mockBackend(page);
    await page.route("**/mission/start", async (route) => {
      capturedBody = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify(START_RESPONSE),
      });
    });

    await page.goto("/");
    await launchMission(page);

    expect((capturedBody!.zone as any)?.geojson_polygon?.type).toBe("Polygon");
    expect(capturedBody!.mission_text).toBe("Scan the area for survivors");
  });

  test("launching transitions to running phase", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/");
    await launchMission(page);
    await expect(page.locator(".header")).toContainText(/RUNNING/i);
    await expect(page.getByRole("button", { name: /end mission/i })).toBeVisible();
  });
});

// ── Tests: running — live updates ─────────────────────────────────────────────

test.describe("running — live updates", () => {
  let mock: Awaited<ReturnType<typeof mockBackend>>;

  test.beforeEach(async ({ page }) => {
    mock = await mockBackend(page);
    await page.goto("/");
    await launchMission(page);
  });

  test("tick renders drone cards", async ({ page }) => {
    await mock.emitTick();
    await page.waitForTimeout(300);
    await expect(page.locator(".nav-section")).toContainText("drone_1");
    await expect(page.locator(".nav-section")).toContainText("drone_2");
    await expect(page.locator(".nav-section")).toContainText("drone_3");
  });

  test("battery percentage shown on drone card", async ({ page }) => {
    await mock.emitTick();
    await page.waitForTimeout(300);
    await expect(page.locator(".nav-section")).toContainText("82%");
  });

  test("coverage ratio updates from tick", async ({ page }) => {
    await mock.emitTick();
    await page.waitForTimeout(300);
    await expect(page.locator(".nav-section")).toContainText("31.3%");
  });

  test("world event appears in event log", async ({ page }) => {
    await mock.emitEvent("battery_low", { drone_id: "drone_2", battery: 23 });
    await page.waitForTimeout(300);
    await expect(page.locator(".nav-section")).toContainText("battery_low");
  });

  test("survivor_found event appears in log", async ({ page }) => {
    await mock.emitEvent("survivor_found", { drone_id: "drone_1", survivor_id: "s1", col: 4, row: 2 });
    await page.waitForTimeout(300);
    await expect(page.locator(".nav-section")).toContainText("survivor_found");
  });
});

// ── Tests: running → paused ───────────────────────────────────────────────────

test.describe("running → paused", () => {
  let mock: Awaited<ReturnType<typeof mockBackend>>;

  test.beforeEach(async ({ page }) => {
    mock = await mockBackend(page);
    await page.goto("/");
    await launchMission(page);
  });

  test("mission_paused SSE transitions UI to paused", async ({ page }) => {
    await mock.emitSSE({ event: "mission_paused", data: { type: "mission_paused", zone_index: 1 } });
    await page.waitForTimeout(300);
    await expect(page.locator(".header")).toContainText(/PAUSED/i);
    await expect(page.locator(".nav-section")).toContainText(/ZONE COMPLETE/i);
  });

  test("resume button disabled until zone 2 is drawn", async ({ page }) => {
    await mock.emitSSE({ event: "mission_paused", data: { type: "mission_paused", zone_index: 1 } });
    await page.waitForTimeout(300);
    await expect(page.getByRole("button", { name: /add zone.*resume/i })).toBeDisabled();

    await drawZone(page);
    await expect(page.getByRole("button", { name: /add zone.*resume/i })).toBeEnabled();
  });

  test("resuming transitions back to running", async ({ page }) => {
    await mock.emitSSE({ event: "mission_paused", data: { type: "mission_paused", zone_index: 1 } });
    await page.waitForTimeout(300);
    await drawZone(page);
    await page.getByRole("button", { name: /add zone.*resume/i }).click();
    await page.waitForTimeout(300);
    await expect(page.locator(".header")).toContainText(/RUNNING/i);
  });
});

// ── Tests: ended ──────────────────────────────────────────────────────────────

test.describe("ended", () => {
  let mock: Awaited<ReturnType<typeof mockBackend>>;

  test.beforeEach(async ({ page }) => {
    mock = await mockBackend(page);
    await page.goto("/");
    await launchMission(page);
  });

  test("end mission button transitions to ended", async ({ page }) => {
    await page.getByRole("button", { name: /end mission/i }).click();
    await page.waitForTimeout(300);
    await expect(page.locator(".header")).toContainText(/ENDED/i);
  });

  test("real mode ended panel is minimal — no sim summary", async ({ page }) => {
    await page.getByRole("button", { name: /end mission/i }).click();
    await page.waitForTimeout(300);
    await expect(page.locator(".nav-section")).not.toContainText(/SIMULATION COMPLETE/i);
    await expect(page.getByRole("button", { name: /new mission/i })).toBeVisible();
  });

  test("new mission resets to pending_zone", async ({ page }) => {
    await page.getByRole("button", { name: /end mission/i }).click();
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: /new mission/i }).click();
    await page.waitForTimeout(200);
    await expect(page.locator(".header")).toContainText(/DRAW ZONE/i);
    await expect(page.getByRole("button", { name: /launch mission/i })).toBeVisible();
  });
});
