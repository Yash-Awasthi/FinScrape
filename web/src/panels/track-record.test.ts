import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import { type Accuracy, api, type Outcome } from "../api";
import { AccuracyPanel, OutcomesPanel, wilson } from "./panels";

const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

afterEach(() => vi.restoreAllMocks());

describe("wilson", () => {
  it("brackets the observed rate and narrows with more calls", () => {
    const [lo, hi] = wilson(60, 100);
    expect(lo).toBeLessThan(0.6);
    expect(hi).toBeGreaterThan(0.6);
    const [lo2, hi2] = wilson(600, 1000);
    expect(hi2 - lo2).toBeLessThan(hi - lo);
    expect(wilson(0, 0)).toEqual([0, 0]);
  });
});

it("shows next-day and vs-SPY rates side by side, with how many calls went unscored", async () => {
  const rate = (hits: number, scored: number) => ({
    hits,
    scored,
    hit_rate: hits / scored,
    by_verdict: { PULL_OUT: { hits, total: scored, hit_rate: hits / scored } },
  });
  vi.spyOn(api, "accuracy").mockResolvedValue({
    ...rate(6, 10),
    total: 14,
    equity_curve: [1, 0, 1],
    equity_metrics: { sharpe_ratio: 0, sortino_ratio: 0, max_drawdown: -0.05 },
    vs_spy: { d2: rate(5, 10), d4: rate(7, 10) },
  } as Accuracy);
  const panel = new AccuracyPanel();
  await panel.load();
  await painted();
  const text = panel.el.textContent ?? "";
  expect(text).toContain("Next day60%6/10");
  expect(text).toContain("+2 days vs SPY50%");
  expect(text).toContain("+4 days vs SPY70%");
  expect(text).toContain("4 of 14 calls moved less than 1%");
  expect(text).toContain("-5.0%");
});

it("marks each scored call right, wrong or still open", async () => {
  vi.spyOn(api, "outcomes").mockResolvedValue([
    {
      event_id: 1,
      subject: "Strait closed to tankers",
      verdict: "PULL_OUT",
      tickers: ["XOM"],
      timestamp: "2026-10-01T00:10:00Z",
      price_move_pct: 2.5,
      correct: true,
      ex2: -0.4,
      ex4: null,
      correct2: false,
      correct4: null,
    },
  ] as Outcome[]);
  const panel = new OutcomesPanel();
  await panel.load();
  await painted();
  const cells = [...panel.el.querySelectorAll("tbody td")].map((td) => td.textContent);
  expect(cells).toEqual([
    "2026-10-01",
    "PULL_OUT",
    "Strait closed to tankers",
    "XOM",
    "✓ +2.5%",
    "✗ -0.4%",
    "open",
  ]);
});
