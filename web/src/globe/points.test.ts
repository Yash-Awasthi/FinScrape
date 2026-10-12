import { describe, expect, it } from "vite-plus/test";
import type { EventOut } from "../api";
import { toPoints } from "./points";

function ev(id: number, lat: number | null, lon: number | null, verdict = "INVEST"): EventOut {
  return {
    id,
    subject: `e${id}`,
    event_type: "geopolitical_event",
    verdict,
    impact_direction: "positive",
    signal_score: 4,
    confidence: 0.7,
    reasoning: "",
    magnitude: "high",
    novelty: "breaking",
    actionability: "high",
    sector_impact: "",
    tickers: [],
    sources: [],
    articles: [],
    affected_entities: [],
    second_order_effects: [],
    key_metrics: {},
    lat,
    lon,
    timestamp: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("toPoints", () => {
  it("drops events without coordinates", () => {
    const pts = toPoints([ev(1, 35.7, 139.7), ev(2, null, 10), ev(3, 10, null)]);
    expect(pts.map((p) => p.id)).toEqual([1]);
    expect(pts[0]).toMatchObject({ lat: 35.7, lng: 139.7 });
  });

  it("colors by verdict and carries the source event", () => {
    const [p] = toPoints([ev(1, 0, 0, "PULL_OUT")]);
    expect(p.color).toBe("#ea3943");
    expect(p.event.id).toBe(1);
  });
});
