// Playwright config for the Launch Pad end-to-end test
// (tests/desktop-launchpad.spec.mjs). The harness serves the runtime's real
// Launch Pad, its bridge and the real backend; it needs the packages in
// server/backend/requirements.txt and requirements-desktop.txt.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.dirname(frontendRoot);
const port = process.env.LAUNCHPAD_HARNESS_PORT || "8767";
const python = process.env.PYTHON || "python3";

export default defineConfig({
  testDir: "./tests",
  testMatch: "desktop-launchpad.spec.mjs",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["line"], ["html", { outputFolder: "playwright-report/desktop-launchpad", open: "never" }]]
    : "line",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "phone-390", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } } },
    { name: "desktop-1280", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } },
  ],
  webServer: {
    command: `${python} frontend/tests/support/launchpad_harness.py --port ${port}`,
    cwd: repositoryRoot,
    url: `http://127.0.0.1:${port}/ready`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
