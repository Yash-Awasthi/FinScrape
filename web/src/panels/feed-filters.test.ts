import { beforeEach, describe, expect, it } from "vite-plus/test";

import type { EventOut } from "../api";
import { filterSearch, NO_FILTERS } from "../app/url-filters";
import { SignalFeedPanel } from "./signal-feed";

const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

function ev(id: number, subject: string, sources: string[]): EventOut {
  return {
    id,
    subject,
    event_type: "geopolitical",
    verdict: "INVEST",
    impact_direction: "positive",
    signal_score: 3,
    confidence: 0.8,
    reasoning: "",
    magnitude: "high",
    novelty: "high",
    actionability: "high",
    sector_impact: "tech",
    tickers: ["AAPL"],
    sources,
    topics: ["energy"],
    articles: [],
    affected_entities: [],
    second_order_effects: [],
    key_metrics: {},
    lat: null,
    lon: null,
    timestamp: null,
    created_at: "2026-06-28T10:00:00Z",
  };
}

const EVENTS = [
  ev(1, "first story", ["world_rss"]),
  ev(2, "second story", ["gdelt"]),
  ev(3, "third story", ["world_rss"]),
];

describe("feed filters in the address bar", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("a clean URL renders no clear-all control", async () => {
    const panel = new SignalFeedPanel(() => {});
    panel.update(EVENTS);
    await painted();
    expect(panel.body.querySelector(".clear-all")).toBeNull();
  });

  it("clicking a verdict chip writes the verdict into the address", async () => {
    const panel = new SignalFeedPanel(() => {});
    panel.update(EVENTS);
    await painted();

    panel.body.querySelector<HTMLElement>('[data-v="INVEST"]')!.click();
    await painted();
    expect(window.location.search).toBe("?v=INVEST");
  });

  it("clear-all resets the chips, the address, and itself", async () => {
    const panel = new SignalFeedPanel(() => {});
    panel.update(EVENTS);
    await painted();

    panel.body.querySelector<HTMLElement>('[data-topic="energy"]')!.click();
    await painted();
    expect(window.location.search).toBe(filterSearch({ ...NO_FILTERS, topic: "energy" }));

    panel.body.querySelector<HTMLElement>(".clear-all")!.click();
    await painted();
    const active = [...panel.body.querySelectorAll<HTMLElement>(".ffilter.active")];
    expect(active).toHaveLength(1);
    expect(active[0].dataset.v).toBe("ALL");
    expect(panel.body.querySelector(".clear-all")).toBeNull();
    expect(window.location.search).toBe("");
  });

  it("a shared URL starts with the lens already applied", async () => {
    window.history.replaceState(null, "", "/?v=BUY&topic=energy");
    const withBuy = [{ ...EVENTS[0], verdict: "BUY" }, EVENTS[1], EVENTS[2]];
    const panel = new SignalFeedPanel(() => {});
    panel.update(withBuy);
    await painted();

    expect(panel.body.querySelector('[data-v="BUY"]')!.classList.contains("active")).toBe(true);
    expect(panel.body.querySelector(".clear-all")).not.toBeNull();
    expect(panel.body.textContent).toContain("first story");
  });
});
