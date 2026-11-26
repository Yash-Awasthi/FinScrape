import { readFileSync } from "node:fs";

import { describe, expect, it } from "vite-plus/test";

import { formatMetric, METRICS, numberCell, type Metric } from "./format";

const EM_DASH = "\u2014";

// Same locale the module uses, so grouping matches whatever the machine does.
const grouped = (value: number, decimals = 2): string =>
  value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

const css = readFileSync("src/styles.css", "utf8");
const chart = readFileSync("src/components/chart.ts", "utf8");

describe("formatMetric", () => {
  it("keeps the same decimals whatever the magnitude", () => {
    expect(formatMetric("price", 1.5)).toBe("1.50 USD");
    expect(formatMetric("price", 5123.45)).toBe(`${grouped(5123.45)} USD`);
    expect(formatMetric("fx", 1.0842)).toBe("1.0842");
    expect(formatMetric("points", 5123.45)).toBe(`${grouped(5123.45)} pts`);
  });

  it("signs gains and drops, and nothing at zero", () => {
    expect(formatMetric("change", 0.456)).toBe("+0.46%");
    expect(formatMetric("change", -1.25)).toBe("-1.25%");
    expect(formatMetric("score", 4)).toBe("+4");
    expect(formatMetric("score", -3)).toBe("-3");
    expect(formatMetric("score", 0)).toBe("0");
  });

  it("always names the unit", () => {
    expect(formatMetric("percent", 3.5).endsWith("%")).toBe(true);
    expect(formatMetric("change", 1.2).endsWith("%")).toBe(true);
    expect(formatMetric("ratio", 2.4).endsWith(":1")).toBe(true);
    expect(formatMetric("tokens", 1200).endsWith(" tokens")).toBe(true);
    expect(formatMetric("seconds", 1.25).endsWith("s")).toBe(true);
    expect(formatMetric("fx", 1.0842)).toMatch(/^[\d.,]+$/);
    expect(formatMetric("brier", 0.5)).toBe("0.500");
  });

  it("shows an em dash for a missing value", () => {
    expect(formatMetric("count", null)).toBe(EM_DASH);
    expect(formatMetric("count", Number.NaN)).toBe(EM_DASH);
  });

  it("wraps a value in a tabular-figure slot", () => {
    expect(numberCell("price", 1.5)).toBe('<span class="num">1.50 USD</span>');
  });

  it("gives every metric one fixed precision", () => {
    const kinds = Object.keys(METRICS) as Metric[];
    expect(kinds.length).toBeGreaterThan(6);
    for (const kind of kinds) {
      const { decimals } = METRICS[kind];
      expect(Number.isInteger(decimals), `${kind} decimals`).toBe(true);
      expect(decimals).toBeGreaterThanOrEqual(0);
      expect(decimals).toBeLessThanOrEqual(4);
    }
  });
});

describe("tabular figures and axis guards", () => {
  it("aligns numbers in columns in the stylesheet", () => {
    expect(css).toContain("font-variant-numeric: tabular-nums");
    const blocks = css.match(/[^{}]+\{[^{}]*font-variant-numeric:\s*tabular-nums[^{}]*\}/g) ?? [];
    expect(blocks.some((block) => block.includes(".num"))).toBe(true);
  });

  it("ships a single y axis", () => {
    const axes = chart.match(/data-axis="y"/g) ?? [];
    expect(axes).toHaveLength(1);
  });
});
