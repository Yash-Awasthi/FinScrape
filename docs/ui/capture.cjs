// Capture the real dashboard at three widths, against docs/ui/serve.cjs fixtures.
//
//   node docs/ui/capture.cjs                  # writes docs/ui/before/<view>-<width>.png
//   node docs/ui/capture.cjs --out=after      # same surfaces into docs/ui/after/
//
// Every image is a viewport screenshot (the spec is width; page heights differ), taken
// after the panel that identifies the view has rendered. Off-origin requests (fonts,
// CDNs) are aborted so the shots cannot depend on the network.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(
  "C:/GITHUB/yash-awasthi/FinScrape/web/node_modules/@playwright/test",
);
const { start, stop } = require("./serve.cjs");

const CHROME = process.env.CHROME_BIN ||
  "C:/Users/Yash/AppData/Local/ms-playwright/chromium-1255/chrome-win64/chrome.exe";
const ORIGIN = "http://127.0.0.1:8099";
const OUT_ARG = process.argv.find((a) => a.startsWith("--out="));
const OUT = path.resolve(__dirname, OUT_ARG ? OUT_ARG.slice("--out=".length) : "before");
const WIDTHS = [
  { width: 360, height: 800 },
  { width: 768, height: 900 },
  { width: 1440, height: 900 },
];

// One entry per surface. `ready` must match before the shot; `before` is the same
// interaction a reader would perform (select a feed row, ask the council, scroll).
const SURFACES = [
  { name: "landing", url: "/", ready: ["#hero-stats"] },
  { name: "today", url: "/app/#today", ready: ['[data-id="feed"] tr[data-event-id]', '[data-id="scenarios"] .sc-card'] },
  {
    name: "desk",
    url: "/app/#desk",
    ready: ['[data-id="desk"] .desk-feed tr[data-event-id]'],
    setup: 'window.dispatchEvent(new CustomEvent("worldfin:followed"))',
  },
  { name: "record", url: "/app/#record", ready: ['[data-id="accuracy"] .acc', '[data-id="outcomes"] tbody tr'] },
  { name: "sources", url: "/app/#sources", ready: ['[data-id="sources"] .src-row', '[data-id="correlations"] .corr-list li'] },
  { name: "event", url: "/app/#/app/event/1", ready: [".event-page"] },
  { name: "scenario", url: "/app/#/app/scenario/s1", ready: [".scenario-page"] },
  {
    name: "ticker",
    url: "/app/#tickers",
    ready: ['[data-id="candles"] .candles-svg'],
    before: 'document.querySelector("[data-id=\\"candles\\"]").scrollIntoView({block:"center"})',
  },
  {
    name: "council",
    url: "/app/#today",
    ready: ['[data-id="feed"] tr[data-event-id]'],
    selectRow: true,
    council: true,
  },
];

async function shoot(browser, surface, size) {
  const context = await browser.newContext({
    viewport: { width: size.width, height: size.height },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
  });
  // Browser-local positions only: the desk's exposure panel counts held symbols, and
  // no server round trip can create them.
  await context.addInitScript(() => {
    try {
      localStorage.setItem(
        "worldfin.positions",
        JSON.stringify([
          { symbol: "XOM", quantity: 120, cost_basis: 104.2 },
          { symbol: "FRO", quantity: 300, cost_basis: 21.8 },
          { symbol: "NVDA", quantity: 40, cost_basis: 172.5 },
        ]),
      );
    } catch {
      /* storage blocked: the panel says there are no positions */
    }
  });
  const page = await context.newPage();

  // Local only. Fonts and any CDN asset are aborted, so the render is offline-stable.
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    return url.origin === ORIGIN ? route.continue() : route.abort();
  });
  // No realtime server: answer the socket with the same rows the REST fixtures serve.
  try {
    await page.routeWebSocket("**/api/ws", (ws) => {
      ws.send(
        JSON.stringify({
          type: "init",
          events: require("./serve.cjs").EVENTS,
          stats: {
            total_events: 9842,
            by_verdict: { INVEST: 2814, OBSERVE: 3902, CAUTIOUS: 2210, PULL_OUT: 916 },
            last_update: new Date(Date.now() - 120_000).toISOString(),
          },
        }),
      );
    });
  } catch (err) {
    console.warn(`websocket mock unavailable: ${err.message}`);
  }

  await page.goto(ORIGIN + surface.url, { waitUntil: "load", timeout: 45_000 });
  // Setup runs before the ready wait: My Desk only loads on the app's own follow event.
  if (surface.setup) await page.evaluate(surface.setup);
  for (const sel of surface.ready) {
    await page.locator(sel).first().waitFor({ state: "visible", timeout: 30_000 });
  }
  if (surface.before) await page.evaluate(surface.before);
  if (surface.selectRow) {
    await page.locator('[data-id="feed"] .row-meta').first().click();
    await page.locator(".inspector .verdict-badge").first().waitFor({ state: "visible", timeout: 15_000 });
  }
  if (surface.council) {
    await page.getByRole("button", { name: "Ask the analyst council" }).click();
    await page.waitForFunction(
      () =>
        [...document.querySelectorAll(".inspector .ai-out")].some((n) =>
          /consensus|dissent|agreement/i.test(n.textContent || ""),
        ),
      null,
      { timeout: 20_000 },
    );
    await page.evaluate(() => {
      const out = [...document.querySelectorAll(".inspector .ai-out")].find((n) =>
        /consensus|dissent|agreement/i.test(n.textContent || ""),
      );
      if (out) out.scrollIntoView({ block: "center" });
    });
  }
  try {
    await page.waitForLoadState("networkidle", { timeout: 10_000 });
  } catch {
    /* a reconnect timer can hold the count open; the selector wait already passed */
  }
  await page.waitForTimeout(1200);

  const file = path.join(OUT, `${surface.name}-${size.width}.png`);
  await page.screenshot({ path: file, fullPage: false });
  const bytes = fs.statSync(file).size;
  await context.close();
  return { file, bytes };
}

function pngWidth(file) {
  const buf = fs.readFileSync(file);
  if (buf.slice(1, 4).toString("ascii") !== "PNG") throw new Error(`${file} is not a PNG`);
  return buf.readUInt32BE(16);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  await start();
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const rows = [];
  let failures = 0;
  try {
    for (const surface of SURFACES) {
      for (const size of WIDTHS) {
        const { file, bytes } = await shoot(browser, surface, size);
        const width = pngWidth(file);
        const ok = bytes > 8 * 1024 && width === size.width;
        if (!ok) failures += 1;
        rows.push({ view: surface.name, width, bytes, ok, file: path.basename(file) });
        console.log(
          `${ok ? "ok  " : "FAIL"} ${path.basename(file)}  ${width}x${bytes} bytes`,
        );
      }
    }
  } finally {
    await browser.close();
    await stop();
  }

  const bad = rows.filter((r) => !r.ok);
  console.log(`\n${rows.length} screenshots, ${bad.length} failed`);
  if (bad.length) {
    for (const r of bad) console.log(`bad: ${r.file} width=${r.width} bytes=${r.bytes}`);
    process.exit(1);
  }
})();
