import { afterEach, expect, it, vi } from "vitest";

import { api, type EventOut, type Prediction, type Reliability } from "../api";
import { PredictionPanel } from "./panels";

const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

afterEach(() => vi.restoreAllMocks());

it("tells same-ticker cards apart by their event and says what the tier means", async () => {
  // Conflict stories all lead with RTX, so three cards read "RTX 52%", "RTX 51%"...
  const table = { global_hit_rate: 0.6, total_weight: 1, sample_size: 1, by_verdict: {}, by_source: {}, by_confidence: {} };
  vi.spyOn(api, "reliability").mockResolvedValue({ reliability: table, brier: { brier: null, n: 0 } } as Reliability);
  const subjects = ["Israeli strikes kill two Gaza officials", "Poland to host a US base"];
  vi.spyOn(api, "events").mockResolvedValue(subjects.map((subject, id) => ({ id, subject, verdict: "PULL_OUT" })) as unknown as EventOut[]);
  vi.spyOn(api, "predict").mockImplementation(async (id: number) => ({
    p_verdict_correct: 0.52, data_tier: "no-outcomes", empirical_share: 0,
    event: { id, subject: subjects[id], verdict: "PULL_OUT", signal_score: -3, ticker: "RTX" },
  }) as unknown as Prediction);
  const panel = new PredictionPanel();
  await panel.load();
  await painted();
  const text = panel.el.textContent ?? "";
  for (const s of subjects) expect(text).toContain(s);
  expect(text).toContain("PULL_OUT · RTX");
  expect(text).toContain("prior only, no outcomes yet");
  expect(text).not.toContain("emp.share");
});
