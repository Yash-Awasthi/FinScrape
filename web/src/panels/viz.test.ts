import { describe, expect, it } from "vite-plus/test";

import {
  VIZ_COLORS,
  barChart,
  calibration,
  columns,
  signColor,
  sparkline,
  stackedBar,
} from "./viz";

describe("viz primitives", () => {
  it("draws nothing rather than a degenerate figure", () => {
    expect(sparkline([])).toBe("");
    expect(sparkline([1])).toBe(""); // a single point is not a trend
    expect(barChart([])).toBe("");
    expect(columns([])).toBe("");
    expect(stackedBar([{ value: 0, color: "#000", label: "none" }])).toBe("");
  });

  it("scales a sparkline to its own range and includes the origin", () => {
    const svg = sparkline([0, 5, 10]);
    expect(svg).toContain("0.0,48.0"); // min pinned to the bottom
    expect(svg).toContain("240.0,0.0"); // max pinned to the top
  });

  it("fills the band with its own range when the origin is excluded", () => {
    // A price series near 200 is a flat line against a zero baseline.
    const zeroed = sparkline([200, 202], "p");
    const ranged = sparkline([200, 202], "p", "#fff", false);
    expect(zeroed).toContain("240.0,0.0");
    expect(zeroed).toContain("0.0,0.5"); // both points pinned near the top
    expect(ranged).toContain("0.0,48.0"); // low anchored to the floor
    expect(ranged).toContain("240.0,0.0");
  });

  it("survives an all-zero series without dividing by zero", () => {
    const svg = sparkline([0, 0, 0]);
    expect(svg).toContain("<polyline");
    expect(svg).not.toContain("NaN");
  });

  it("scales bars against the largest magnitude, not the sum", () => {
    const html = barChart([
      { label: "a", value: 10 },
      { label: "b", value: 5 },
    ]);
    expect(html).toContain("width:100%");
    expect(html).toContain("width:50%");
  });

  it("uses magnitude for bar length so negatives still render", () => {
    expect(barChart([{ label: "loss", value: -8 }])).toContain("width:100%");
  });

  it("gives every column a visible floor", () => {
    expect(columns([100, 0])).toContain("height:2%"); // zero stays clickable
  });

  it("splits a stacked bar proportionally and drops empty segments", () => {
    const html = stackedBar([
      { value: 3, color: "#0f0", label: "bull" },
      { value: 1, color: "#f00", label: "bear" },
      { value: 0, color: "#888", label: "flat" },
    ]);
    expect(html).toContain("width:75%");
    expect(html).toContain("width:25%");
    expect(html).not.toContain("flat:");
  });

  it("escapes labels into the aria text", () => {
    expect(barChart([{ label: "<img src=x>", value: 1 }])).not.toContain("<img");
  });

  it("draws no calibration curve without a usable point", () => {
    expect(calibration([])).toBe("");
    expect(calibration([{ predicted: 0.5, observed: Number.NaN, weight: 1, label: "x" }])).toBe("");
  });

  it("places a calibration point by predicted x and observed y", () => {
    // 160 box, 12 pad, 136 span: predicted .5 -> x 80, observed 1 -> y 12 (top).
    const svg = calibration([{ predicted: 0.5, observed: 1, weight: 1, label: "b" }]);
    expect(svg).toContain('cx="80.0"');
    expect(svg).toContain('cy="12.0"');
  });

  it("colours a point by which side of the diagonal it falls on", () => {
    const under = calibration([{ predicted: 0.3, observed: 0.9, weight: 1, label: "u" }]);
    const over = calibration([{ predicted: 0.9, observed: 0.3, weight: 1, label: "o" }]);
    expect(under).toContain(VIZ_COLORS.up);
    expect(over).toContain(VIZ_COLORS.down);
  });

  it("orders calibration points by predicted value, whatever order they arrive in", () => {
    const svg = calibration([
      { predicted: 0.9, observed: 0.9, weight: 1, label: "hi" },
      { predicted: 0.1, observed: 0.1, weight: 1, label: "lo" },
    ]);
    const path = /d="M([\d.]+)/.exec(svg);
    expect(Number(path![1])).toBeLessThan(80); // starts at the low bucket
  });

  it("clamps an out-of-range rate into the box", () => {
    const svg = calibration([{ predicted: 2, observed: -1, weight: 1, label: "bad" }]);
    expect(svg).toContain('cx="148.0"');
    expect(svg).toContain('cy="148.0"');
  });

  it("sizes calibration dots by weight", () => {
    const svg = calibration([
      { predicted: 0.2, observed: 0.2, weight: 1, label: "thin" },
      { predicted: 0.8, observed: 0.8, weight: 100, label: "thick" },
    ]);
    const radii = [...svg.matchAll(/r="([\d.]+)"/g)].map((m) => Number(m[1]));
    expect(radii[0]).toBeLessThan(radii[1]);
  });

  it("colours by sign", () => {
    expect(signColor(1)).not.toBe(signColor(-1));
    expect(signColor(0)).toBe(signColor(0));
  });
});
