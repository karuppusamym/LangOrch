import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright e2e test configuration for LangOrch frontend.
 *
 * The tests require:
 *   - Next.js dev server on http://localhost:3000  (auto-started via webServer below)
 *   - LangOrch backend API on http://localhost:8000  (must be started separately)
 *
 * To skip the backend requirement in CI, set:
 *   BACKEND_URL=http://your-backend:8000
 *
 * Run:
 *   npm run test:e2e               # headless Chromium
 *   npm run test:e2e:ui            # interactive Playwright UI
 */

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,       // sequential to avoid race conditions against shared backend
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
