import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config — mocked backend, real Chromium browser.
 *
 * Frontend dev server must be running on port 3000 before running tests.
 * Backend is NOT required — all /mission/* requests are intercepted.
 *
 * Run:
 *   cd tests/e2e
 *   bun install
 *   bunx playwright install chromium
 *   bunx playwright test
 */
export default defineConfig({
  testDir: "./specs",
  fullyParallel: false,   // sequential — tests share UI state assumptions
  retries: 0,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },

  reporter: [
    ["list"],
    ["html", { outputFolder: "report", open: "never" }],
  ],

  use: {
    baseURL: "http://localhost:3000",
    browserName: "chromium",
    headless: true,
    viewport: { width: 1280, height: 800 },
    // Capture trace + screenshot on failure only
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
