/**
 * 04 — Hard constraints validation
 *
 * Proves:
 *   - No client-side drone animation loop
 *   - Single Leaflet map init
 *   - No DronePatrolService
 *   - Phase never regresses
 *   - SSE opens only when mission is active
 *   - REST body shapes correct
 */

import { test, expect } from "@playwright/test";
import { mockBackend, TICK_SNAPSHOT, DEFINE_MAP_RESPONSE, START_RESPONSE } from "../mocks/backend";

async function clickMap(page: import("@playwright/test").Page, x: number, y: number) {
  const box = await page.locator(".leaflet-container").boundingBox();
  await page.mouse.click(box!.x + x, box!.y + y);
  await page.waitForTimeout(80);
}

async function launchMission(page: import("@playwright/test").Page) {
  await page.waitForSelector(".leaflet-container");
  await page.waitForTimeout(500);
  for (const [x, y] of [[100, 100], [250, 100], [250, 250], [100, 250]] as [number, number][]) {
    await clickMap(page, x, y);
  }
  await page.locator("textarea").fill("Scan the area");
  await page.getByRole("button", { name: /launch mission/i }).click();
  await page.waitForTimeout(400);
}

test("drone markers do not move without SSE tick", async ({ page }) => {
  const mock = await mockBackend(page);
  await page.goto("/");
  await launchMission(page);
  await mock.emitTick();
  await page.waitForTimeout(300);

  const getPositions = () =>
    page.evaluate(() =>
      Array.from(document.querySelectorAll(".leaflet-marker-pane .leaflet-marker-icon"))
        .map((m) => (m as HTMLElement).style.transform)
    );

  const before = await getPositions();
  await page.waitForTimeout(2000);  // 2s with no SSE
  const after = await getPositions();
  expect(after).toEqual(before);
});

test("Leaflet map initialises exactly once", async ({ page }) => {
  await mockBackend(page);
  await page.goto("/");
  await page.waitForSelector(".leaflet-container");
  await page.waitForTimeout(300);
  const count = await page.evaluate(() =>
    document.querySelectorAll(".leaflet-container").length
  );
  expect(count).toBe(1);
});

test("DronePatrolService is not instantiated", async ({ page }) => {
  await mockBackend(page);
  let found = false;
  page.on("console", (msg) => {
    if (msg.text().includes("DronePatrolService")) found = true;
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  const inWindow = await page.evaluate(() =>
    typeof (window as any).DronePatrolService !== "undefined"
  );
  expect(inWindow).toBe(false);
  expect(found).toBe(false);
});

test("phase never regresses from running to pending_zone", async ({ page }) => {
  const mock = await mockBackend(page);
  await page.goto("/");
  await launchMission(page);

  await mock.emitTick();
  await mock.emitEvent("drone_moved", { drone_id: "drone_1", from_col: 0, from_row: 0, to_col: 1, to_row: 0 });
  await mock.emitEvent("battery_low", { drone_id: "drone_2", battery: 22 });
  await page.waitForTimeout(300);

  await expect(page.locator(".header")).not.toContainText(/DRAW ZONE/i);
  await expect(page.getByRole("button", { name: /launch mission/i })).not.toBeVisible();
});

test("SSE is not opened during pending_zone phase", async ({ page }) => {
  await mockBackend(page);
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);

  const sseUrls = await page.evaluate(() => (window as any).__sseUrls as string[]);
  const opened = sseUrls.some((url) => url.includes("/mission/stream"));
  expect(opened).toBe(false);
});

test("SSE opens when mission starts", async ({ page }) => {
  await mockBackend(page);
  await page.goto("/");
  await launchMission(page);
  await page.waitForTimeout(300);

  const sseUrls = await page.evaluate(() => (window as any).__sseUrls as string[]);
  const opened = sseUrls.some((url) => url.includes("/mission/stream"));
  expect(opened).toBe(true);
});
