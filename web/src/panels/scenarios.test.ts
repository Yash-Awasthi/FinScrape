import { afterEach, describe, expect, it, vi } from "vitest";

import { api, type Portfolio, type Scenario } from "../api";
import { ScenarioPanel } from "./panels";

// setContent paints on the next animation frame.
const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

const scenario = (overrides: Partial<Scenario> = {}): Scenario => ({
  id: "s1",
  title: "Strait closed to tankers",
  size: 3,
  reports: 5,
  probability: 0.72,
  direction: "down",
  stance: "risk-off",
  tilt: -0.44,
  data_tier: "empirical",
  sample_size: 13,
  divergent_members: 0,
  sectors: [{ name: "transport", direction: "down", strength: 1, tilt: -0.9 }],
  exposure: [
    { name: "XOM", direction: "up", strength: 1, tilt: 0.8 },
    { name: "SHEL", direction: "down", strength: 0.5, tilt: -0.4 },
  ],
  chain: ["Freight rates spike"],
  advice: "Risk-off: reduce transport; add energy.",
  member_ids: [1, 2, 3],
  sources: ["reuters/world"],
  first_seen: null,
  ...overrides,
});

const portfolio = (tickers: string[]): Portfolio => ({
  positions: tickers.map((ticker) => ({ ticker, shares: 10, avg_cost: 1 })),
  watchlists: [],
  summary: {},
});

async function mount(
  scenarios: Scenario[],
  held: string[] = [],
  portfolioFails = false,
): Promise<ScenarioPanel> {
  vi.spyOn(api, "scenarios").mockResolvedValue(scenarios);
  vi.spyOn(api, "portfolio").mockImplementation(() =>
    portfolioFails ? Promise.reject(new Error("no portfolio")) : Promise.resolve(portfolio(held)),
  );
  const panel = new ScenarioPanel();
  await panel.load();
  await painted();
  return panel;
}

afterEach(() => vi.restoreAllMocks());

describe("ScenarioPanel", () => {
  it("leads with the instruction, not the evidence", async () => {
    const panel = await mount([scenario()]);
    const advice = panel.el.querySelector(".sc-advice")!;
    expect(advice.textContent).toBe("Risk-off: reduce transport; add energy.");
    expect(panel.el.querySelector(".sc-prob")!.textContent).toBe("72%");
  });

  it("marks exposure the user actually holds", async () => {
    const panel = await mount([scenario()], ["XOM"]);
    const chips = [...panel.el.querySelectorAll<HTMLElement>(".sc-tk")];
    const byName = Object.fromEntries(chips.map((c) => [c.dataset.sym, c]));
    expect(byName.XOM.classList.contains("sc-held")).toBe(true);
    expect(byName.SHEL.classList.contains("sc-held")).toBe(false);
  });

  it("still advises when the portfolio is unreachable", async () => {
    const panel = await mount([scenario()], [], true);
    expect(panel.el.querySelector(".sc-advice")).not.toBeNull();
    expect(panel.el.querySelector(".sc-held")).toBeNull();
  });

  it("re-aims the chart when a ticker chip is clicked", async () => {
    const panel = await mount([scenario()]);
    const seen: string[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent<string>).detail);
    window.addEventListener("worldfin:select-symbol", listener);
    panel.el.querySelector<HTMLElement>('.sc-tk[data-sym="SHEL"]')!.click();
    window.removeEventListener("worldfin:select-symbol", listener);
    expect(seen).toEqual(["SHEL"]);
  });

  it("warns when the sources inside a scenario disagreed", async () => {
    const panel = await mount([scenario({ divergent_members: 2 })]);
    expect(panel.el.querySelector(".sc-warn")!.textContent).toBe("2 divergent");
  });

  it("stays quiet about divergence when there is none", async () => {
    const panel = await mount([scenario()]);
    expect(panel.el.querySelector(".sc-warn")).toBeNull();
  });

  it("counts reports, not cluster members", async () => {
    // Ingest merges same-story coverage into one event, so `size` is ~always 1
    // and would read "1 report" for a story five outlets carried.
    const panel = await mount([scenario({ size: 1, reports: 5 })]);
    expect(panel.el.querySelector(".sc-meta")!.textContent).toContain("5 reports");
  });

  it("shows how many outcomes back the tier", async () => {
    const panel = await mount([scenario({ data_tier: "thin-data", sample_size: 13 })]);
    expect(panel.el.querySelector(".sc-meta")!.textContent).toContain("thin record (13 scored calls)");
  });

  it("does not say '1 reports'", async () => {
    const panel = await mount([scenario({ size: 1, reports: 1 })]);
    expect(panel.el.querySelector(".sc-meta")!.textContent).toContain("1 report ");
  });

  it("explains an empty board rather than rendering a blank panel", async () => {
    const panel = await mount([]);
    expect(panel.el.querySelector(".empty")!.textContent).toContain("No scenario has formed");
  });

  it("escapes a hostile title instead of executing it", async () => {
    const panel = await mount([scenario({ title: '<img src=x onerror=alert(1)>' })]);
    expect(panel.el.querySelector("img")).toBeNull();
    expect(panel.el.querySelector(".sc-title")!.textContent).toContain("<img");
  });

  it("says so when the engine is down", async () => {
    vi.spyOn(api, "portfolio").mockResolvedValue(portfolio([]));
    vi.spyOn(api, "scenarios").mockRejectedValue(new Error("502"));
    const panel = new ScenarioPanel();
    await panel.load();
    await painted();
    expect(panel.el.querySelector(".empty")!.textContent).toContain("unavailable");
  });
});
