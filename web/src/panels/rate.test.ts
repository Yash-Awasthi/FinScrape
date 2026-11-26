import { describe, expect, it } from "vite-plus/test";

import { MIN_SAMPLE, hasSample, rateText } from "./rate";

describe("minimum sample", () => {
  it("is 20 calls", () => {
    expect(MIN_SAMPLE).toBe(20);
  });

  it("renders n=19 as insufficient sample, not a number", () => {
    expect(rateText(19, 0.67)).toBe("insufficient sample");
    expect(hasSample(19)).toBe(false);
  });

  it("renders n=20 as the rate", () => {
    expect(rateText(20, 0.67)).toBe("67%");
    expect(hasSample(20)).toBe(true);
  });

  it("treats a missing rate as insufficient even with a large n", () => {
    expect(rateText(50, null)).toBe("insufficient sample");
    expect(rateText(null, 0.5)).toBe("insufficient sample");
  });
});
