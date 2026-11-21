import { describe, expect, it } from "vite-plus/test";

import { hitLabel, hitValue, sampleLabel, spyLabel, windowLabel } from "./rates";

// plan m1.4.3: no rate on the landing page without n, the window it covers and an
// interval. These labels are the whole surface for that rule, so they are tested
// as text rather than through the DOM.

describe("landing rate labels", () => {
  const wide = {
    scored: 3,
    hit_rate: 0.667,
    sample: "n=3, 21–94% · wide interval",
    window: { from: "2026-11-01T00:00:00+00:00", to: "2026-11-20T00:00:00+00:00" },
  };

  it("quotes the sample size, the interval and the window for a real rate", () => {
    const acc = {
      ...wide,
      scored: 42,
      hit_rate: 0.595,
      sample: "n=42, 45–73% · ±14 pts",
      vs_spy: { d4: { scored: 40, hit_rate: 0.55, sample: "n=40, 40–69%" } },
    };
    expect(hitValue(acc)).toBe("60%");
    const label = hitLabel(acc);
    expect(label).toContain("n=42, 45–73% · ±14 pts");
    expect(label).toContain("2026-11-01 to 2026-11-20");
    expect(label).toContain("moved the way called");
  });

  it("shows a count and no rate below the minimum sample", () => {
    expect(hitValue(wide)).toBe("3");
    const label = hitLabel(wide);
    expect(label).toContain("no rate until 30");
    expect(label).toContain("2026-11-01 to 2026-11-20");
    expect(label).not.toContain("%");
  });

  it("falls back to n= when the API sent no sample string", () => {
    expect(sampleLabel({ scored: 7, hit_rate: 0.5 })).toBe("n=7");
    const label = hitLabel({ scored: 40, hit_rate: 0.5 });
    expect(label).toContain("n=40");
    expect(label).toContain("no scored calls yet");
  });

  it("names a missing window rather than inventing one", () => {
    expect(windowLabel(undefined)).toBe("no scored calls yet");
    expect(windowLabel({ from: null, to: null })).toBe("no scored calls yet");
    expect(windowLabel({ from: "2026-11-01T00:00:00", to: null })).toBe("2026-11-01 to now");
  });

  it("prints n and interval for both SPY horizons", () => {
    const label = spyLabel({
      d2: { scored: 30, hit_rate: 0.5, sample: "n=30, 33–67%" },
      d4: { scored: 28, hit_rate: 0.54, sample: "n=28, 36–71%" },
    });
    expect(label).toBe("+4 days vs SPY: n=28, 36–71% (+2 days: n=30, 33–67%)");
  });
});
