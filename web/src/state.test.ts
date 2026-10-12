import { describe, expect, it } from "vite-plus/test";
import type { EventOut } from "./api";
import { Store } from "./state";

function ev(id: number, over: Partial<EventOut> = {}): EventOut {
  return {
    id,
    subject: `e${id}`,
    event_type: "other",
    verdict: "OBSERVE",
    impact_direction: "neutral",
    signal_score: 0,
    confidence: 0.5,
    reasoning: "",
    magnitude: "medium",
    novelty: "standard",
    actionability: "medium",
    sector_impact: "",
    tickers: [],
    sources: [],
    articles: [],
    affected_entities: [],
    second_order_effects: [],
    key_metrics: {},
    lat: null,
    lon: null,
    timestamp: null,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("Store", () => {
  it("addEvents prepends, dedups by id, newest-first", () => {
    const s = new Store();
    s.setEvents([ev(1), ev(2)]);
    s.addEvents([ev(3), ev(2)]); // 2 is a dup
    const ids = s.get().events.map((e) => e.id);
    expect(ids).toEqual([3, 2, 1]);
  });

  it("notifies subscribers and reflects connection", () => {
    const s = new Store();
    const seen: string[] = [];
    s.subscribe((st) => seen.push(st.connection));
    s.setConnection("open");
    expect(seen.at(-1)).toBe("open");
  });
});
