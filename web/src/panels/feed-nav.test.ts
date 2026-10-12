import { beforeEach, describe, expect, it, vi } from "vite-plus/test";

import type { EventOut } from "../api";
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

describe("feed keyboard navigation", () => {
  let panel: SignalFeedPanel;
  let selected: number[];

  beforeEach(async () => {
    selected = [];
    panel = new SignalFeedPanel((e) => selected.push(e.id));
    panel.update(EVENTS);
    await painted();
  });

  const activeSubject = () =>
    panel.body.querySelector("tr.active")?.querySelector(".subj")?.textContent;

  it("enters at the top on the first j and walks down", () => {
    panel.moveSelection(1);
    expect(activeSubject()).toBe("first story");
    panel.moveSelection(1);
    expect(activeSubject()).toBe("second story");
    expect(selected).toEqual([1, 2]);
  });

  it("enters at the bottom on the first k", () => {
    panel.moveSelection(-1);
    expect(activeSubject()).toBe("third story");
  });

  it("stops at the ends instead of wrapping", () => {
    panel.moveSelection(-1); // bottom
    panel.moveSelection(1);
    expect(activeSubject()).toBe("third story");
    for (let i = 0; i < 5; i++) panel.moveSelection(-1);
    expect(activeSubject()).toBe("first story");
  });

  it("keeps the selection across a live re-render", async () => {
    panel.moveSelection(1);
    panel.moveSelection(1);
    expect(activeSubject()).toBe("second story");
    // A WS push prepends a row: the selected story must not be dropped or shift.
    panel.update([ev(9, "breaking", ["world_rss"]), ...EVENTS]);
    await painted();
    expect(activeSubject()).toBe("second story");
  });

  it("clears the active row", () => {
    panel.moveSelection(1);
    panel.clearActive();
    expect(panel.body.querySelector("tr.active")).toBeNull();
  });
});

describe("feed source filter", () => {
  it("narrows to one source and the chip clears it", async () => {
    const panel = new SignalFeedPanel(() => {});
    panel.update(EVENTS);
    await painted();

    window.dispatchEvent(new CustomEvent("worldfin:select-source", { detail: "gdelt" }));
    await painted();
    expect(panel.body.querySelectorAll("table.feed tbody tr")).toHaveLength(1);
    expect(panel.body.textContent).toContain("second story");

    const chip = panel.body.querySelector<HTMLElement>("[data-source]");
    expect(chip).not.toBeNull();
    chip!.click();
    await painted();
    expect(panel.body.querySelectorAll("table.feed tbody tr")).toHaveLength(3);
  });

  it("selecting the same source twice clears it", async () => {
    const panel = new SignalFeedPanel(() => {});
    panel.update(EVENTS);
    await painted();
    const fire = (s: string) =>
      window.dispatchEvent(new CustomEvent("worldfin:select-source", { detail: s }));
    fire("world_rss");
    await painted();
    expect(panel.body.querySelectorAll("table.feed tbody tr")).toHaveLength(2);
    fire("world_rss");
    await painted();
    expect(panel.body.querySelectorAll("table.feed tbody tr")).toHaveLength(3);
  });
});

describe("row click", () => {
  it("selects the whole row, including the headline link", async () => {
    const picked: number[] = [];
    const panel = new SignalFeedPanel((e) => picked.push(e.id));
    const withLink = { ...EVENTS[0], articles: ["https://example.com/a"] };
    panel.update([withLink]);
    await painted();
    // Clicking the link used to select nothing, so a click could land on a row and
    // leave the inspector empty.
    panel.body.querySelector<HTMLElement>(".subj a")!.click();
    expect(picked).toEqual([1]);
    expect(panel.body.querySelector("tr.active")).not.toBeNull();
    vi.restoreAllMocks();
  });
});
