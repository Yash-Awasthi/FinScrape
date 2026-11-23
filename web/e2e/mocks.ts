import type { Page } from "@playwright/test";

// EventOut fixture matching server/schemas.py + src/api.ts. Only the fields the UI
// reads need to be realistic; the rest are filled with sane defaults.
export function ev(id: number, subject: string, tickers: string[], verdict = "INVEST") {
  return {
    id,
    subject,
    event_type: "geopolitical",
    verdict,
    impact_direction: "positive",
    signal_score: 42,
    confidence: 0.8,
    reasoning: `Why ${subject} matters.`,
    magnitude: "high",
    novelty: "high",
    actionability: "high",
    sector_impact: "tech",
    tickers,
    sources: ["reuters", "ap"],
    articles: ["https://example.com/a"],
    affected_entities: [{ name: "Apple", ticker: "AAPL", role: "supplier", impact: "up" }],
    second_order_effects: [],
    key_metrics: {},
    lat: 37.77,
    lon: -122.41,
    timestamp: "2026-06-28T10:00:00Z",
    created_at: "2026-06-28T10:00:00Z",
  };
}

export const INIT_EVENTS = [
  ev(1, "Chip export controls tightened", ["AAPL", "MSFT"]),
  ev(2, "Energy supply shock in Europe", ["XOM"], "CAUTIOUS"),
];
export const NEW_EVENT = ev(3, "Breaking: central bank surprise hike", ["JPM"], "OBSERVE");

export const STATS = {
  total_events: 2,
  by_verdict: { INVEST: 1, CAUTIOUS: 1 },
  last_update: "2026-06-28T10:00:00Z",
};

// Fulfill every REST call the dashboard makes on load. Shapes mirror src/api.ts.
export async function mockBackend(page: Page): Promise<void> {
  // Keep this suite local, including third-party images and embedded media.
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    return url.origin === "http://127.0.0.1:4183" ? route.continue() : route.abort();
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (() => {
      if (path.endsWith("/api/events")) return { events: INIT_EVENTS };
      if (path.endsWith("/api/stats")) return STATS;
      if (path.endsWith("/api/dates")) return { dates: [] };
      if (path.endsWith("/api/correlations")) return { correlations: [] };
      if (path.endsWith("/api/health")) return { status: "ok", db: true, llm: false, sources: [] };
      if (path.endsWith("/api/accuracy"))
        return { total: 0, scored: 0, hits: 0, hit_rate: 0, by_verdict: {}, equity_curve: [] };
      if (path.endsWith("/api/outcomes")) return { outcomes: [] };
      if (path.endsWith("/api/suggestions")) return { suggestions: [] };
      if (path.endsWith("/api/storylines")) return { storylines: [] };
      if (path.endsWith("/api/scenarios")) return { scenarios: [] };
      if (path.endsWith("/api/sectors")) return { sectors: [] };
      if (path.endsWith("/api/market/quotes"))
        return { quotes: [], as_of: "2026-06-28T10:00:00Z", symbols: [] };
      return {};
    })();
    await route.fulfill({ json });
  });

  // Mock the WebSocket entirely (no real server): push `init`, then a `new_events`
  // frame after the initial REST load has surely settled, to exercise live update.
  await page.routeWebSocket("**/api/ws", (ws) => {
    ws.send(JSON.stringify({ type: "init", events: INIT_EVENTS, stats: STATS }));
    setTimeout(() => {
      ws.send(
        JSON.stringify({
          type: "new_events",
          events: [NEW_EVENT],
          stats: { ...STATS, total_events: 3 },
        }),
      );
    }, 1200);
  });
}
