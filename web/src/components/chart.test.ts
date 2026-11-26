import { describe, expect, it } from "vite-plus/test";

import { sparkline } from "../panels/viz";
import { chart, formatTick, niceTicks } from "./chart";

describe("chart", () => {
  it("states an empty series rather than drawing an empty box", () => {
    const html = chart({ values: [], label: "calls", emptyHint: "no calls in this window" });
    expect(html).toContain('data-state="empty"');
    expect(html).toContain("no data yet");
    expect(html).toContain("no calls in this window");
  });

  it("calls an all-zero series no-data instead of a flat measured line", () => {
    const html = chart({ values: [0, 0, 0], label: "calls" });
    expect(html).toContain('data-state="no-data"');
    expect(html).not.toContain("<polyline");
    expect(html).not.toContain("0,0");
  });

  it("draws exactly one y axis, with the unit once on the caption", () => {
    const svg = chart({ values: [1, 2, 4], label: "hit rate", unit: "%", decimals: 0 });
    // "no y2" is the design rule: a second scale would imply a correlation.
    expect((svg.match(/data-axis=/g) ?? []).length).toBe(1);
    expect(svg).toContain('data-axis="y"');
    expect(svg).not.toContain('data-axis="y2"');
    expect(svg).toContain("hit rate (%)");
  });

  it("writes every tick with the same fixed decimals", () => {
    const svg = chart({ values: [0, 0.5, 1], decimals: 2, fromZero: true, label: "share" });
    expect(svg).toContain("0.50");
    expect(svg).toContain("1.00");
  });

  it("picks round tick steps people read without arithmetic", () => {
    expect(niceTicks(0, 10)).toEqual([0, 5, 10]);
    const halves = niceTicks(0, 1);
    expect(halves).toContain(0);
    expect(halves).toContain(1);
    expect(Number((halves[1] - halves[0]).toFixed(1))).toBe(0.5);
    expect(niceTicks(5, 5)).toEqual([5]);
  });

  it("keeps one precision for every tick", () => {
    expect(formatTick(2, 1)).toBe("2.0");
    expect(formatTick(2.345, 2)).toBe("2.35");
  });

  it("spells the series out for screen readers", () => {
    const svg = chart({ values: [1, 2, 4], label: "calls", unit: "events" });
    expect(svg).toContain('aria-label="calls in events: 3 points, 0 to 4"');
  });

  it("keeps the sparkline frame unchanged, minus its own plotter", () => {
    const svg = sparkline([0, 5, 10]);
    expect(svg).toContain("0.0,48.0"); // min pinned to the bottom of the 240x48 box
    expect(svg).toContain("240.0,0.0"); // max pinned to the top
    expect(sparkline([])).toBe("");
    expect(sparkline([0, 0, 0])).toContain('data-state="no-data"');
    expect(sparkline([0, 0, 0])).not.toContain("<polyline");
  });
});
