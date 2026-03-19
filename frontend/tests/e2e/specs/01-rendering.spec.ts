/**
 * 01 — Rendering validation
 *
 * Proves the browser actually renders what we designed:
 *   - Dark background (not plain white)
 *   - Sidebar present and correct width
 *   - Leaflet map fills the viewport
 *   - CSS variables applied
 *   - Correct phase panel on load (draw zone, not define map)
 */

import { test, expect } from "@playwright/test";
import { mockBackend } from "../mocks/backend";

test.beforeEach(async ({ page }) => {
  await mockBackend(page);
  await page.goto("/");
  await page.waitForLoadState("networkidle");
});

test("page background is dark not white", async ({ page }) => {
  const bg = await page.evaluate(() =>
    getComputedStyle(document.body).backgroundColor
  );
  expect(bg).not.toBe("rgb(255, 255, 255)");
  expect(bg).not.toBe("rgba(0, 0, 0, 0)");
});

test("sidebar is present and correct width", async ({ page }) => {
  const sidebar = page.locator(".sidebar");
  await expect(sidebar).toBeVisible();
  const box = await sidebar.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThanOrEqual(280);
  expect(box!.width).toBeLessThanOrEqual(360);
});

test("sidebar header shows MultiUAV Console", async ({ page }) => {
  await expect(page.locator(".header h1")).toContainText("MultiUAV");
});

test("phase shows DRAW ZONE on load (no pending_map phase)", async ({ page }) => {
  const header = page.locator(".header");
  await expect(header).toContainText(/DRAW ZONE/i);
});

test("LAUNCH MISSION button is visible on load", async ({ page }) => {
  await expect(page.getByRole("button", { name: /launch mission/i })).toBeVisible();
});

test("LAUNCH MISSION button is disabled with no zone drawn", async ({ page }) => {
  await expect(page.getByRole("button", { name: /launch mission/i })).toBeDisabled();
});

test("Leaflet map container is visible and fills available space", async ({ page }) => {
  const map = page.locator(".leaflet-container");
  await expect(map).toBeVisible();
  const box = await map.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThan(600);
  expect(box!.height).toBeGreaterThan(400);
});

test("Leaflet map has dark background", async ({ page }) => {
  const bg = await page.locator(".leaflet-container").evaluate((el) =>
    getComputedStyle(el).backgroundColor
  );
  expect(bg).not.toBe("rgb(255, 255, 255)");
});

test("Enter Simulation Mode button visible in real mode", async ({ page }) => {
  await expect(page.getByRole("button", { name: /simulation mode/i })).toBeVisible();
});

test("glass utility applies correct non-white background", async ({ page }) => {
  const glass = page.locator(".glass").first();
  await expect(glass).toBeVisible();
  const bg = await glass.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).not.toBe("rgb(255, 255, 255)");
});

test("main content area fills remaining horizontal space", async ({ page }) => {
  const sidebarBox = await page.locator(".sidebar").boundingBox();
  const mainBox = await page.locator(".main-content").boundingBox();
  expect(sidebarBox).not.toBeNull();
  expect(mainBox).not.toBeNull();
  expect(mainBox!.x).toBeCloseTo(sidebarBox!.x + sidebarBox!.width, -1);
  expect(mainBox!.width + sidebarBox!.width).toBeGreaterThan(1100);
});
