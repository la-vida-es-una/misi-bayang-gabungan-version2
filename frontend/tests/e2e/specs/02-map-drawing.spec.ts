/**
 * 02 — Map drawing validation
 *
 * Proves zone polygon drawing works:
 *   - Clicking the map adds vertex markers
 *   - Right-click clears polygon
 *   - 3+ points + mission text enables LAUNCH MISSION
 *   - Drawing hint visible and scoped to map area
 */

import { test, expect } from "@playwright/test";
import { mockBackend } from "../mocks/backend";

test.beforeEach(async ({ page }) => {
  await mockBackend(page);
  await page.goto("/");
  await page.waitForSelector(".leaflet-container");
  await page.waitForTimeout(500);
});

async function clickMap(page: import("@playwright/test").Page, x: number, y: number) {
  const box = await page.locator(".leaflet-container").boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.click(box!.x + x, box!.y + y);
  await page.waitForTimeout(100);
}

test("clicking map 3 times adds 3 vertex markers", async ({ page }) => {
  await clickMap(page, 100, 100);
  await clickMap(page, 200, 100);
  await clickMap(page, 150, 200);
  const markers = page.locator(".leaflet-marker-pane .leaflet-marker-icon");
  await expect(markers).toHaveCount(3);
});

test("zone point counter updates as points are added", async ({ page }) => {
  await clickMap(page, 100, 100);
  await expect(page.locator(".nav-section")).toContainText("1");
  await clickMap(page, 200, 100);
  await expect(page.locator(".nav-section")).toContainText("2");
  await clickMap(page, 150, 200);
  await expect(page.locator(".nav-section")).toContainText("3");
});

test("LAUNCH MISSION enables only after 3 points AND mission text", async ({ page }) => {
  const btn = page.getByRole("button", { name: /launch mission/i });
  await expect(btn).toBeDisabled();

  await clickMap(page, 100, 100);
  await clickMap(page, 200, 100);
  await clickMap(page, 150, 200);
  await expect(btn).toBeDisabled();  // no mission text yet

  await page.locator("textarea").fill("Scan the area");
  await expect(btn).toBeEnabled();
});

test("right-click clears zone polygon and disables button", async ({ page }) => {
  await clickMap(page, 100, 100);
  await clickMap(page, 200, 100);
  await clickMap(page, 150, 200);
  await page.locator("textarea").fill("Scan the area");
  await expect(page.getByRole("button", { name: /launch mission/i })).toBeEnabled();

  const box = await page.locator(".leaflet-container").boundingBox();
  await page.mouse.click(box!.x + 150, box!.y + 150, { button: "right" });
  await page.waitForTimeout(100);

  await expect(page.locator(".leaflet-marker-pane .leaflet-marker-icon")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /launch mission/i })).toBeDisabled();
});

test("drawing hint is scoped to map container", async ({ page }) => {
  // Use scoped locator to avoid strict mode violation if text appears elsewhere
  const hint = page.locator(".map-container").getByText(/Right-click to clear/i);
  await expect(hint).toBeVisible();
});
