import { afterEach, expect, it, vi } from "vite-plus/test";

import {
  probabilityChart,
  probabilityLine,
  renderScenarioPage,
  type ScenarioDetail,
  type WhatIf,
} from "./scenario";

const DETAIL: ScenarioDetail = {
  scenario: {
    id: "s7",
    title: "Tankers stop in the strait",
    size: 2,
    reports: 4,
    probability: 0.74,
    ci95: [0.6, 0.88],
    n_members: 2,
    direction: "down",
    stance: "risk-off",
    tilt: -0.4,
    data_tier: "empirical",
    sample_size: 12,
    divergent_members: 0,
    sectors: [{ name: "energy", direction: "down", strength: 1, tilt: -0.4 }],
    exposure: [{ name: "XOM", direction: "down", strength: 1, tilt: -0.3 }],
    chain: [],
    advice: "Reduce energy exposure.",
    member_ids: [7, 8],
    sources: ["reuters/world"],
    first_seen: "2026-05-03T09:00:00+00:00",
  },
  members: [
    {
      id: 7,
      subject: "Tankers stop",
      verdict: "PULL_OUT",
      signal_score: -4,
      confidence: 0.8,
      sector_impact: "energy",
      timestamp: "2026-05-03T09:00:00+00:00",
      sources: ["reuters"],
    },
  ],
  window: { events_considered: 42, event_cap: 200, lookback_days: 14 },
};

it("states the probability with its member count and interval", () => {
  expect(probabilityLine(DETAIL.scenario)).toBe("74% ? 2 member calls ? 95% interval 60-88%");
  expect(probabilityLine({ ...DETAIL.scenario, ci95: null, n_members: 1 })).toContain(
    "one member carries no spread",
  );
});

it("shows the members, the tilt, the exposed tickers and the window", () => {
  const page = renderScenarioPage(DETAIL);
  const text = page.textContent ?? "";
  expect(text).toContain("Tankers stop in the strait");
  expect(text).toContain("Reduce energy exposure.");
  expect(text).toContain("energy");
  expect(text).toContain("XOM");
  expect(text).toContain("Window: the last 200 analysed events over 14 days (42 considered)");
  const link = page.querySelector('a[href="/app/event/7"]');
  expect(link?.textContent).toBe("Tankers stop");
});

const HISTORY = [
  { probability: 0.61, n_members: 2, at: "2026-05-03T08:00:00+00:00" },
  { probability: 0.74, n_members: 2, at: "2026-05-03T10:00:00+00:00" },
];

it("draws the history on a fixed 50-100% axis and needs two points for a line", () => {
  expect(probabilityChart(HISTORY.slice(0, 1))).toBeNull();
  expect(probabilityChart([])).toBeNull();
  const svg = probabilityChart(HISTORY) ?? "";
  expect(svg).toContain("2 recomputes, 61 to 74 percent");
  expect(svg).toContain("<polyline");
  // 61% sits below 74%: the first point is lower on screen (larger y).
  const [first, second] = /points="([^ ]+) ([^"]+)"/.exec(svg)!.slice(1, 3);
  expect(Number(first.split(",")[1])).toBeGreaterThan(Number(second.split(",")[1]));
});

it("shows the stored history on the page, and says when there is none", () => {
  const withHistory = renderScenarioPage({ ...DETAIL, history: HISTORY });
  expect(withHistory.textContent).toContain("Probability history");
  expect(withHistory.textContent).toContain("2 stored recomputes from");
  expect(withHistory.querySelector("svg.sc-spark")).not.toBeNull();
  const without = renderScenarioPage(DETAIL);
  expect(without.textContent).toContain("one number and no trend");
  expect(without.querySelector("svg.sc-spark")).toBeNull();
});

it("says when there is no interval rather than printing a fake one", () => {
  const page = renderScenarioPage({
    ...DETAIL,
    scenario: { ...DETAIL.scenario, ci95: null, n_members: 1 },
  });
  expect(page.textContent).toContain("no interval");
});

const WHAT_IF: WhatIf = {
  excluded_id: 7,
  probability: 0.82,
  n_members: 1,
  ci95: null,
  label: "hypothetical: this member removed",
};

it("marks a what-if as hypothetical, above the members and away from the stored call", () => {
  const page = renderScenarioPage({ ...DETAIL, what_if: WHAT_IF });
  const text = page.textContent ?? "";
  expect(text).toContain("Hypothetical: event #7 removed");
  expect(text).toContain("Probability 82% (n=1) - not the stored scenario.");
  // The stored call is still on the page; the strip is a second number, labelled.
  expect(text).toContain("74%");
  const strip = page.querySelector("section.ev-block");
  const members = [...page.querySelectorAll("h2")].find((h) => h.textContent === "Member events");
  expect(strip).not.toBeNull();
  expect(strip!.contains(members ?? null)).toBe(false);
});

it("offers the stored scenario back and shows no strip when nothing was excluded", () => {
  const page = renderScenarioPage({ ...DETAIL, what_if: WHAT_IF });
  const buttons = [...page.querySelectorAll("button")];
  expect(buttons.some((b) => b.textContent === "Restore the real scenario")).toBe(true);
  expect(renderScenarioPage(DETAIL).textContent).not.toContain("Hypothetical");
});

it("puts a hide-and-recompute button beside each member link, never inside it", () => {
  const page = renderScenarioPage(DETAIL);
  const button = page.querySelector("li button.story-toggle");
  expect(button?.textContent).toBe("Hide and recompute");
  expect(button?.closest("a")).toBeNull();
  expect(page.querySelector('a[href="/app/event/7"]')?.contains(button!)).toBe(false);
});

afterEach(() => {
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

it("refetches with the excluded member, then restores without the param", async () => {
  const calls: string[] = [];
  const fakeFetch = vi.fn(async (url: string) => {
    calls.push(url);
    const body = url.includes("exclude=") ? { ...DETAIL, what_if: WHAT_IF } : DETAIL;
    return { ok: true, status: 200, json: async () => body };
  });
  vi.stubGlobal("fetch", fakeFetch);

  const page = renderScenarioPage(DETAIL);
  document.body.append(page);
  (page.querySelector("button.story-toggle") as HTMLButtonElement).click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  expect(calls).toEqual(["/api/scenarios/s7?exclude=7"]);
  expect(document.body.textContent).toContain("Hypothetical: event #7 removed");

  const restore = [...document.body.querySelectorAll("button")].find(
    (b) => b.textContent === "Restore the real scenario",
  ) as HTMLButtonElement;
  restore.click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  expect(calls).toEqual(["/api/scenarios/s7?exclude=7", "/api/scenarios/s7"]);
  expect(document.body.textContent).not.toContain("Hypothetical");
});
