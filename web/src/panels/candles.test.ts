import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api";
import { CandlesPanel } from "./panels";

const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

const candle = (t: string, c: number) => ({ t, o: c - 1, h: c + 1, l: c - 2, c, v: 1000 });

afterEach(() => vi.restoreAllMocks());

describe("CandlesPanel", () => {
  it("draws the chart on first load instead of staying on Loading", async () => {
    vi.spyOn(api, "candles").mockResolvedValue({
      symbol: "AAPL",
      candles: [candle("2026-09-01", 100), candle("2026-09-02", 102), candle("2026-09-03", 101)],
    });
    const panel = new CandlesPanel();
    await panel.load();
    await painted();
    expect(panel.el.querySelector(".candles-body svg")).not.toBeNull();
    expect(panel.el.textContent).not.toContain("Loading…");
  });
});
