import { defineConfig, devices } from "@playwright/test";

// Full-stack E2E: the built SPA against the real API and a seeded Postgres. Kept out
// of `npx playwright test` because CI has no database. Run with `npm run e2e:live`
// and WORLDFIN_TEST_DATABASE_URL pointing at a database whose name ends in `_test`.
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
      command: `${python} -m server.seed && ${python} -m server.main`,
      cwd: "..",
      url: `${api}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        WORLDFIN_DATABASE_URL: db,
        WORLDFIN_HOST: "127.0.0.1",
        WORLDFIN_PORT: "8012",
        // Unreachable on purpose: embeddings degrade at once instead of waiting on Ollama.
        OLLAMA_HOST: "http://127.0.0.1:9",
        FINSCRAPE_LAYA: "0",
      },
    },
    {
      command: "npm run build && npm run preview -- --host 127.0.0.1 --port 4184 --strictPort",
      url: "http://127.0.0.1:4184",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { WORLDFIN_API_URL: api },
    },
  ],
});
