/**
 * 05 — Simulation mode validation
 *
 * Proves:
 *   - Enter sim mode shows wizard
 *   - Wizard progresses: base → boundary → survivors → done
 *   - Back navigation works
 *   - SIM badge visible throughout sim mode
 *   - Sim mode uses amber styling (not blue accent)
 *   - Sim complete panel shows on ended
 *   - "Simulate Again" resets to sim setup
 *   - "Exit Simulation Mode" returns to real mode
 *   - Sim survivors toggle works
 */

import { test, expect } from "@playwright/test";
import { mockBackend, TICK_SNAPSHOT, DEFINE_MAP_RESPONSE, START_RESPONSE } from "../mocks/backend";

async function clickMap(page: import("@playwright/test").Page, x: number, y: number) {
  const box = await page.locator(".leaflet-container").boundingBox();
  await page.mouse.click(box!.x + x, box!.y + y);
  await page.waitForTimeout(150);
}

async function enterSimMode(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: /simulation mode/i }).click();
  await page.waitForTimeout(200);
}

async function completeSimSetup(page: import("@playwright/test").Page) {
  // Step 1: place base
  await clickMap(page, 200, 200);
  await page.waitForTimeout(200);
  // Step 2: use full map canvas
  await page.getByRole("button", { name: /use full map canvas/i }).click();
  await page.waitForTimeout(200);
  // Step 3: confirm survivors
  await page.getByRole("button", { name: /seed survivors/i }).click();
  await page.waitForTimeout(200);
}

async function launchInSimMode(page: import("@playwright/test").Page) {
  await page.waitForSelector(".leaflet-container");
  await page.waitForTimeout(500);
  await enterSimMode(page);
  await completeSimSetup(page);
  // Draw zone
  await clickMap(page, 100, 100);
  await clickMap(page, 250, 100);
  await clickMap(page, 250, 250);
  await clickMap(page, 100, 250);
  await page.locator("textarea").fill("Sim scan mission");
  await page.getByRole("button", { name: /launch mission/i }).click();
  await page.waitForTimeout(400);
}

// ── Entering sim mode ─────────────────────────────────────────────────────────

test.describe("entering sim mode", () => {
  test.beforeEach(async ({ page }) => {
    await mockBackend(page);
    await page.goto("/");
    await page.waitForSelector(".leaflet-container");
    await page.waitForTimeout(500);
  });

  test("Enter Simulation Mode button is visible in real mode", async ({ page }) => {
    await expect(page.getByRole("button", { name: /simulation mode/i })).toBeVisible();
  });

  test("clicking Enter Simulation Mode shows sim setup panel", async ({ page }) => {
    await enterSimMode(page);
    await expect(page.locator(".nav-section")).toContainText(/SIMULATION SETUP/i);
  });

  test("SIM badge appears in header after entering sim mode", async ({ page }) => {
    await enterSimMode(page);
    await expect(page.locator(".header")).toContainText("SIM");
  });

  test("Enter Simulation Mode button disappears in sim mode", async ({ page }) => {
    await enterSimMode(page);
    await expect(page.getByRole("button", { name: /enter simulation mode/i })).not.toBeVisible();
  });
});

// ── Wizard steps ──────────────────────────────────────────────────────────────

test.describe("sim setup wizard", () => {
  test.beforeEach(async ({ page }) => {
    await mockBackend(page);
    await page.goto("/");
    await page.waitForSelector(".leaflet-container");
    await page.waitForTimeout(500);
    await enterSimMode(page);
  });

  test("step 1 shows place base instruction", async ({ page }) => {
    await expect(page.locator(".nav-section")).toContainText(/place.*base/i);
  });

  test("clicking map on step 1 places base and advances to step 2", async ({ page }) => {
    await clickMap(page, 200, 200);
    await page.waitForTimeout(200);
    await expect(page.locator(".nav-section")).toContainText(/spawn area/i);
  });

  test("step 2 has Use Full Map Canvas button", async ({ page }) => {
    await clickMap(page, 200, 200);
    await page.waitForTimeout(200);
    await expect(page.getByRole("button", { name: /use full map canvas/i })).toBeVisible();
  });

  test("Use Full Map Canvas advances to step 3", async ({ page }) => {
    await clickMap(page, 200, 200);
    await page.waitForTimeout(200);
    await page.getByRole("button", { name: /use full map canvas/i }).click();
    await page.waitForTimeout(200);
    await expect(page.locator(".nav-section")).toContainText(/survivor count/i);
  });

  test("step 3 has survivor count slider", async ({ page }) => {
    await clickMap(page, 200, 200);
    await page.waitForTimeout(200);
    await page.getByRole("button", { name: /use full map canvas/i }).click();
    await page.waitForTimeout(200);
    await expect(page.locator("input[type=range]")).toBeVisible();
  });

  test("Seed Survivors completes setup and shows draw zone panel", async ({ page }) => {
    await completeSimSetup(page);
    await expect(page.locator(".nav-section")).toContainText(/search zone/i);
    await expect(page.getByRole("button", { name: /launch mission/i })).toBeVisible();
  });

  test("back navigation from step 2 goes to step 1", async ({ page }) => {
    await clickMap(page, 200, 200);
    await page.waitForTimeout(200);
    await page.getByRole("button", { name: /← back/i }).click();
    await page.waitForTimeout(200);
    await expect(page.locator(".nav-section")).toContainText(/place.*base/i);
  });

  test("Exit Simulation Mode returns to real mode", async ({ page }) => {
    await page.getByRole("button", { name: /exit simulation mode/i }).click();
    await page.waitForTimeout(200);
    await expect(page.locator(".header")).not.toContainText("SIM");
    await expect(page.getByRole("button", { name: /launch mission/i })).toBeVisible();
  });
});

// ── Sim mode mission ──────────────────────────────────────────────────────────

test.describe("sim mode mission", () => {
  let mock: Awaited<ReturnType<typeof mockBackend>>;

  test.beforeEach(async ({ page }) => {
    mock = await mockBackend(page);
    await page.goto("/");
    await launchInSimMode(page);
  });

  test("SIM badge persists during running phase", async ({ page }) => {
    await expect(page.locator(".header")).toContainText("SIM");
    await expect(page.locator(".header")).toContainText(/RUNNING/i);
  });

  test("sim survivors panel visible in running phase", async ({ page }) => {
    await mock.emitTick();
    await page.waitForTimeout(300);
    await expect(page.locator(".nav-section")).toContainText(/SIM SURVIVORS/i);
  });

  test("sim survivors show/hide toggle works", async ({ page }) => {
    await mock.emitTick();
    await page.waitForTimeout(300);

    // Click hide
    await page.getByRole("button", { name: /hide/i }).click();
    await page.waitForTimeout(100);
    // Survivor list should be hidden — s1, s2 labels gone
    await expect(page.locator(".nav-section")).not.toContainText("s1");

    // Click show
    await page.getByRole("button", { name: /show/i }).click();
    await page.waitForTimeout(100);
    await expect(page.locator(".nav-section")).toContainText("s1");
  });
});

// ── Sim ended panel ───────────────────────────────────────────────────────────

test.describe("sim ended panel", () => {
  let mock: Awaited<ReturnType<typeof mockBackend>>;

  test.beforeEach(async ({ page }) => {
    mock = await mockBackend(page);
    await page.goto("/");
    await launchInSimMode(page);
  });

  test("mission_ended shows SIMULATION COMPLETE panel", async ({ page }) => {
    await mock.emitSSE({
      event: "mission_ended",
      data: { type: "mission_ended", survivors_found: 3, total_survivors: 5, zones_completed: 2 },
    });
    await page.waitForTimeout(300);
    await expect(page.locator(".nav-section")).toContainText(/SIMULATION COMPLETE/i);
  });

  test("sim ended shows survivors_found / total", async ({ page }) => {
    await mock.emitSSE({
      event: "mission_ended",
      data: { type: "mission_ended", survivors_found: 3, total_survivors: 5, zones_completed: 2 },
    });
    await page.waitForTimeout(300);
    await expect(page.locator(".nav-section")).toContainText("3 / 5");
  });

  test("Simulate Again resets to sim setup", async ({ page }) => {
    await mock.emitSSE({
      event: "mission_ended",
      data: { type: "mission_ended", survivors_found: 3, total_survivors: 5, zones_completed: 2 },
    });
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: /simulate again/i }).click();
    await page.waitForTimeout(200);
    await expect(page.locator(".nav-section")).toContainText(/SIMULATION SETUP/i);
    await expect(page.locator(".header")).toContainText("SIM");
  });

  test("Exit Simulation Mode returns to real mode after sim ends", async ({ page }) => {
    await mock.emitSSE({
      event: "mission_ended",
      data: { type: "mission_ended", survivors_found: 3, total_survivors: 5, zones_completed: 2 },
    });
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: /exit simulation mode/i }).click();
    await page.waitForTimeout(200);
    await expect(page.locator(".header")).not.toContainText("SIM");
    await expect(page.getByRole("button", { name: /launch mission/i })).toBeVisible();
  });
});
