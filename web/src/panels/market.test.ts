import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import { api, type Quote } from "../api";
import { MarketPanel } from "./market";

const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

const quote = (overrides: Partial<Quote> = {}): Quote => ({
  symbol: "^GSPC",
  price: 5123.45,
  previous_close: 5100,
  change_percent: 0.46,
  spark: [5100, 5110, 5123.45],
  ...overrides,
});

async function mount(quotes: Quote[]): Promise<MarketPanel> {
  vi.spyOn(api, "quotes").mockResolvedValue({
    quotes,
    as_of: "2026-11-23T18:00:00Z",
    symbols: quotes.map((q) => q.symbol),
  });
  const panel = new MarketPanel();
  await panel.load();
  await painted();
  return panel;
}

afterEach(() => vi.restoreAllMocks());

describe("MarketPanel", () => {
  it("renders one labelled tile per quote with a signed change", async () => {
    const panel = await mount([
      quote(),
      quote({ symbol: "CL=F", price: 81.1, change_percent: -1.25, spark: [83, 82, 81.1] }),
    ]);
    const tiles = panel.body.querySelectorAll(".mkt-tile");
    expect(tiles).toHaveLength(2);
    expect(panel.body.textContent).toContain("S&P 500");
    expect(panel.body.textContent).toContain("▲ +0.46%");
    expect(panel.body.textContent).toContain("▼ -1.25%");
    expect(panel.body.textContent).toContain("Crude");
    // Prices name their unit: index points for ^GSPC, dollars for a future.
    expect(panel.body.textContent).toContain("pts");
    expect(panel.body.textContent).toContain("USD");
  });

  it("clicking a tile opens that symbol's chart", async () => {
    const picked: string[] = [];
    const handler = (e: Event) => picked.push((e as CustomEvent<string>).detail);
    window.addEventListener("worldfin:select-symbol", handler);
    const panel = await mount([quote({ symbol: "NVDA" })]);
    panel.body.querySelector<HTMLElement>(".mkt-tile")!.click();
    window.removeEventListener("worldfin:select-symbol", handler);
    expect(picked).toEqual(["NVDA"]);
  });

  it("says so when the market feed returns nothing", async () => {
    const panel = await mount([]);
    expect(panel.body.textContent).toContain("No quotes resolved");
  });
});
