// Browser proof for the PWA checklist row: installable manifest, offline app shell,
// and a 200-event read cache served when the network is gone.
//
// Serves web/dist itself (SPA fallback for /app/) with a fixture API, because the
// real backend is not part of this gate. Run from web/: `node src/pwa/verify.mjs`.

import http from "node:http";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { extname, join, resolve, sep } from "node:path";
import { tmpdir } from "node:os";
import { chromium } from "@playwright/test";

const DIST = resolve(process.cwd(), "dist");
const EVENT_COUNT = 205;
const KEPT = 200;
const NEWEST_ID = EVENT_COUNT;
const OLDEST_ID = 1;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
};

function fixtureEvent(id) {
  return {
    id,
    subject: `Cached story ${id}`,
    event_type: "geopolitical",
    verdict: "INVEST",
    impact_direction: "positive",
    signal_score: 42,
    confidence: 0.8,
    reasoning: `Why Cached story ${id} matters.`,
    magnitude: "high",
    novelty: "high",
    actionability: "high",
    sector_impact: "tech",
    sector: "tech",
    tickers: ["AAPL"],
    sources: ["reuters", "ap"],
    articles: ["https://example.com/a"],
    affected_entities: [{ name: "Apple", ticker: "AAPL", role: "supplier", impact: "up" }],
    second_order_effects: [],
    key_metrics: {},
    lat: 37.77,
    lon: -122.41,
    timestamp: "2026-11-26T09:00:00Z",
    created_at: "2026-11-26T09:00:00Z",
  };
}

// Ascending ids: the newest rows are at the end, which is what trimEvents slices.
const FIXTURE_EVENTS = Array.from({ length: EVENT_COUNT }, (_, i) => fixtureEvent(i + 1));

const STATS = {
  total_events: EVENT_COUNT,
  by_verdict: { INVEST: EVENT_COUNT },
  last_update: "2026-11-26T09:00:00Z",
  ingest_interval_minutes: 15,
};

function apiJSON(pathname) {
  if (pathname === "/api/events") return { events: FIXTURE_EVENTS };
  if (pathname.startsWith("/api/events/")) {
    const id = Number(pathname.split("/").pop());
    return FIXTURE_EVENTS.find((e) => e.id === id) ?? {};
  }
  if (pathname === "/api/stats") return STATS;
  if (pathname === "/api/health") return { status: "ok", db: true, llm: false, sources: [] };
  if (pathname === "/api/dates") return { dates: [] };
  if (pathname === "/api/correlations") return { correlations: [] };
  if (pathname === "/api/accuracy")
    return { total: 0, scored: 0, hits: 0, hit_rate: 0, by_verdict: {}, equity_curve: [] };
  if (pathname === "/api/outcomes") return { outcomes: [] };
  if (pathname === "/api/suggestions") return { suggestions: [] };
  if (pathname === "/api/storylines") return { storylines: [] };
  if (pathname === "/api/scenarios") return { scenarios: [] };
  if (pathname === "/api/sectors") return { sectors: [] };
  if (pathname === "/api/watchlists") return { watchlists: [] };
  if (pathname === "/api/market/quotes")
    return { quotes: [], as_of: "2026-11-26T09:00:00Z", symbols: [] };
  if (pathname.startsWith("/api/candles")) return { symbol: "AAPL", candles: [] };
  if (pathname === "/api/reliability") return { reliability: {}, brier: {} };
  if (pathname.startsWith("/api/predict")) return {};
  return {};
}

function sendJSON(res, body) {
  const bytes = Buffer.from(JSON.stringify(body));
  res.writeHead(200, {
    "content-type": "application/json; charset=utf-8",
    "content-length": bytes.length,
    "cache-control": "no-store",
  });
  res.end(bytes);
}

function serveStatic(req, res) {
  const url = new URL(req.url ?? "/", "http://127.0.0.1");
  const pathname = decodeURIComponent(url.pathname);
  let file = join(DIST, pathname);
  // Directory URL -> directory index.html.
  if (pathname.endsWith("/")) file = join(file, "index.html");
  if (!file.startsWith(DIST + sep) && file !== DIST) {
    res.writeHead(403);
    res.end("forbidden");
    return;
  }
  if (!existsSync(file) || !statSync(file).isFile()) {
    // SPA fallback: the dashboard lives at /app/ and routes by hash, so any
    // unmatched app path still gets the shell; everything else gets the landing page.
    file = join(DIST, "app", "index.html");
    if (!existsSync(file)) file = join(DIST, "index.html");
  }
  if (!existsSync(file)) {
    res.writeHead(404);
    res.end("not found");
    return;
  }
  const bytes = readFileSync(file);
  res.writeHead(200, {
    "content-type": MIME[extname(file)] ?? "application/octet-stream",
    "content-length": bytes.length,
    "cache-control": "no-store",
  });
  res.end(bytes);
}

const server = http.createServer((req, res) => {
  const pathname = new URL(req.url ?? "/", "http://127.0.0.1").pathname;
  if (pathname.startsWith("/api/")) {
    sendJSON(res, apiJSON(pathname));
    return;
  }
  serveStatic(req, res);
});
// The dashboard opens a websocket; refusing the upgrade leaves the connection
// status closed, which is the offline-adjacent path we care about here.
server.on("upgrade", (_req, socket) => socket.destroy());

let failures = 0;
function pass(name) {
  console.log(`PASS ${name}`);
}
function fail(name, detail) {
  failures += 1;
  console.log(`FAIL ${name}${detail ? `: ${detail}` : ""}`);
}
function check(name, cond, detail) {
  if (cond) pass(name);
  else fail(name, detail);
}

function withTimeout(promise, ms, fallback) {
  return Promise.race([promise, new Promise((r) => setTimeout(() => r(fallback), ms))]);
}

const userDataDir = mkdtempSync(join(tmpdir(), "finscrape-pwa-"));

async function main() {
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const { port } = server.address();
  const origin = `http://127.0.0.1:${port}`;
  console.log(`serve dist: ${DIST}`);
  console.log(`origin: ${origin}`);

  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: true,
    executablePath: process.env.CHROME_BIN,
    args: ["--no-sandbox"],
  });
  const page = context.pages()[0] ?? (await context.newPage());
  page.on("console", (m) => {
    if (m.type() === "error") console.log(`[page error] ${m.text()}`);
  });
  page.on("pageerror", (e) => console.log(`[page exception] ${e.message}`));

  // ---- b) load the app, wait for the worker, inspect the manifest --------------
  try {
    await page.goto(`${origin}/app/`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  } catch (e) {
    fail("load /app/", e.message);
  }

  const swReady = await withTimeout(
    page
      .evaluate(() => {
        if (!("serviceWorker" in navigator)) return false;
        return navigator.serviceWorker.ready.then(
          () => true,
          () => false,
        );
      })
      .catch(() => false),
    15_000,
    false,
  );
  check("service worker becomes ready", swReady === true);

  let manifestHref = null;
  try {
    await page.waitForSelector('link[rel="manifest"]', { timeout: 5_000, state: "attached" });
    manifestHref = await page.getAttribute('link[rel="manifest"]', "href");
  } catch {
    /* reported below */
  }
  check("manifest link present", typeof manifestHref === "string" && manifestHref.length > 0);

  if (manifestHref) {
    const manifestURL = new URL(manifestHref, `${origin}/app/`).href;
    const res = await context.request.get(manifestURL);
    check("manifest link resolves 200", res.status() === 200, `status ${res.status()}`);
    let manifest = null;
    try {
      manifest = await res.json();
    } catch (e) {
      fail("manifest parses as JSON", e.message);
    }
    if (manifest) {
      check("manifest name", typeof manifest.name === "string" && manifest.name.length > 0);
      check(
        "manifest short_name",
        typeof manifest.short_name === "string" && manifest.short_name.length > 0,
      );
      check("manifest start_url is /app/", manifest.start_url === "/app/", manifest.start_url);
      check("manifest scope is /", manifest.scope === "/", manifest.scope);
      check("manifest display standalone", manifest.display === "standalone", manifest.display);
      check("manifest theme_color", /^#[0-9a-f]{6}$/i.test(manifest.theme_color ?? ""));
      check("manifest background_color", /^#[0-9a-f]{6}$/i.test(manifest.background_color ?? ""));

      const icons = Array.isArray(manifest.icons) ? manifest.icons : [];
      for (const size of ["192x192", "512x512"]) {
        const icon = icons.find((i) => i.sizes === size);
        if (!icon) {
          fail(`manifest icon ${size} declared`);
          continue;
        }
        pass(`manifest icon ${size} declared`);
        const iconURL = new URL(icon.src, manifestURL).href;
        const iconRes = await context.request.get(iconURL);
        check(`icon ${size} returns 200`, iconRes.status() === 200, `status ${iconRes.status()}`);
        const body = await iconRes.body();
        const sig = [...body.subarray(0, 8)];
        check(
          `icon ${size} is a PNG`,
          sig.join(",") === "137,80,78,71,13,10,26,10",
          `signature ${sig.join(",")}`,
        );
      }
    }
  }

  // ---- c) reload so the worker controls the page -------------------------------
  try {
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
  } catch (e) {
    fail("reload under service worker", e.message);
  }
  const controlled = await withTimeout(
    page.evaluate(() => Boolean(navigator.serviceWorker?.controller)).catch(() => false),
    10_000,
    false,
  );
  check("service worker controls the page after reload", controlled === true);

  // ---- d) the events cache holds the newest 200 --------------------------------
  const cacheReady = await withTimeout(
    page
      .waitForFunction(
        async () => {
          if (!("caches" in window)) return false;
          for (const name of await caches.keys()) {
            const cache = await caches.open(name);
            if (await cache.match("/api/events")) return true;
          }
          return false;
        },
        undefined,
        { timeout: 20_000 },
      )
      .then(() => true)
      .catch(() => false),
    25_000,
    false,
  );
  check(
    "cache storage has /api/events",
    cacheReady === true,
    `keys ${JSON.stringify(await page.evaluate(() => caches.keys()).catch(() => []))}`,
  );

  const cached = cacheReady
    ? await page
        .evaluate(async () => {
          const out = { found: false, body: null, cachedAt: null };
          for (const name of await caches.keys()) {
            const cache = await caches.open(name);
            const hit = await cache.match("/api/events");
            if (hit) {
              out.found = true;
              out.body = await hit.json();
              const meta = await cache.match("/__pwa_meta__");
              if (meta) out.cachedAt = (await meta.json()).cachedAt ?? null;
              break;
            }
          }
          return out;
        })
        .catch((e) => ({ found: false, body: null, cachedAt: null, error: e.message }))
    : { found: false, body: null, cachedAt: null };

  if (cached.found && cached.body) {
    const events = Array.isArray(cached.body.events) ? cached.body.events : [];
    check("cached events length is 200", events.length === KEPT, `length ${events.length}`);
    const ids = events.map((e) => e.id);
    check(`cached newest id ${NEWEST_ID} kept`, ids.includes(NEWEST_ID));
    check(`cached oldest id ${OLDEST_ID} trimmed`, !ids.includes(OLDEST_ID));
    check("cached events are newest-first", ids[0] === NEWEST_ID, `first id ${ids[0]}`);
    check(
      "cached events are the newest by id",
      ids.length > 0 && Math.min(...ids) === EVENT_COUNT - KEPT + 1,
      `min id ${ids.length ? Math.min(...ids) : "none"}`,
    );
  }
  const cachedAt = typeof cached.cachedAt === "number" ? cached.cachedAt : null;
  check("cache stores a cachedAt timestamp", cachedAt !== null, String(cached.cachedAt));

  // ---- e) offline reload: stale banner + cached rows render --------------------
  await context.setOffline(true);
  try {
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
  } catch (e) {
    fail("offline reload served by service worker", e.message);
  }

  let bannerText = null;
  try {
    await page.waitForSelector("[data-pwa-offline]", { timeout: 15_000, state: "visible" });
    bannerText = (await page.textContent("[data-pwa-offline]")) ?? "";
  } catch {
    /* reported below */
  }
  check(
    "offline banner contains required text",
    typeof bannerText === "string" && bannerText.includes("Offline - showing cached events"),
    String(bannerText),
  );
  check(
    "offline banner shows the cached timestamp",
    typeof bannerText === "string" &&
      /\(cached \d{1,2} [A-Z][a-z]{2} \d{4}, \d{2}:\d{2} UTC\)/.test(bannerText),
    String(bannerText),
  );

  try {
    await page.waitForFunction(
      () => document.body.innerText.split("\n").some((l) => l.trim() === `Cached story ${205}`),
      undefined,
      { timeout: 15_000 },
    );
  } catch {
    /* reported below */
  }
  const bodyLines = await page
    .evaluate(() => document.body.innerText.split("\n").map((l) => l.trim()))
    .catch(() => []);
  const storyLines = bodyLines.filter((l) => l.startsWith("Cached story "));
  const storyDetail = `rendered rows ${storyLines.length}, first ${storyLines[0] ?? "none"}, last ${storyLines.at(-1) ?? "none"}`;
  check(
    "cached newest event subject renders offline",
    bodyLines.includes("Cached story 205"),
    storyDetail,
  );
  check(
    "trimmed oldest event subject is absent",
    !bodyLines.includes("Cached story 1"),
    storyDetail,
  );

  // ---- f) summary --------------------------------------------------------------
  await context.close();
}

main()
  .catch((e) => fail("verify crashed", e.stack ?? e.message))
  .finally(async () => {
    server.close();
    try {
      rmSync(userDataDir, { recursive: true, force: true });
    } catch {
      /* best effort */
    }
    if (failures) {
      console.log(`\nFAILED ${failures} assertion${failures === 1 ? "" : "s"}`);
      process.exitCode = 1;
    } else {
      console.log("\nPASS all assertions");
      process.exitCode = 0;
    }
  });
