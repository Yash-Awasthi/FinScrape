import { defineConfig, devices } from "@playwright/test";

// E2E drives the real built SPA (vite preview) with REST + WS fully mocked in the
// browser (see e2e/dashboard.spec.ts) — no backend/DB needed, so it's deterministic
// and CI-fast. The full-stack run lives in playwright.live.config.ts.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "list" : "line",
  use: {
    baseURL: "http://127.0.0.1:4183",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run build && npm run preview -- --host 127.0.0.1 --port 4183 --strictPort",
    url: "http://127.0.0.1:4183",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
