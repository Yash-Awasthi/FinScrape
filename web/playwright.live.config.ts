import { defineConfig, devices } from "@playwright/test";

// Real API + seeded SQL, with a test-only environment and upstream network guard.
// The database must be empty, on an explicit 127.0.0.1 port, and named *_test.
const db = process.env.WORLDFIN_TEST_DATABASE_URL ?? "";
if (!/_test(\?|$)/.test(db)) {
  throw new Error("WORLDFIN_TEST_DATABASE_URL must name a *_test database");
}
const python =
  process.env.PYTHON ??
  (process.platform === "win32" ? ".venv\\Scripts\\python" : ".venv/bin/python");
const api = "http://127.0.0.1:8012";

export default defineConfig({
  testDir: "./e2e-live",
  timeout: 60_000,
  expect: { timeout: 20_000 },
  reporter: "line",
  use: { baseURL: "http://127.0.0.1:4184" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${python}" -m tests.live_e2e api`,
      cwd: "..",
      url: `${api}/ready`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        WORLDFIN_TEST_DATABASE_URL: db,
      },
    },
    {
      command: `"${python}" -m tests.live_e2e web`,
      cwd: "..",
      url: "http://127.0.0.1:4184",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { WORLDFIN_TEST_DATABASE_URL: db },
    },
  ],
});
