import { describe, expect, it } from "vite-plus/test";

import { sourceBadge } from "./signal-feed";

// The badge is the only place a reader learns a row is keyword output rather than a model
// verdict, so it must appear for exactly those rows (plan m1.3.2).
describe("sourceBadge", () => {
  it("labels heuristic and repaired rows", () => {
    expect(sourceBadge("heuristic")).toContain("heuristic");
    expect(sourceBadge("heuristic")).toContain("keyword fallback");
    expect(sourceBadge("model_repaired")).toContain("repaired");
  });

  it("marks rows written before the source was recorded", () => {
    expect(sourceBadge("unknown")).toContain("src?");
  });

  it("keeps model-judged rows clean", () => {
    expect(sourceBadge("model")).toBe("");
    expect(sourceBadge(undefined)).toBe("");
  });
});
