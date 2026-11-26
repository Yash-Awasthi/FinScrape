import { expect, it } from "vite-plus/test";

import {
  backingSentence,
  corroboration,
  renderEventPage,
  sectorChain,
  type EventPageData,
} from "./event";

const EVENT: EventPageData = {
  id: 7,
  subject: "Exxon lifts production guidance",
  event_type: "guidance",
  verdict: "INVEST",
  impact_direction: "positive",
  signal_score: 4,
  confidence: 0.71,
  reasoning: "Production rose and the company raised guidance.",
  magnitude: "high",
  novelty: "breaking",
  actionability: "high",
  sector_impact: "energy",
  tickers: ["XOM", "CVX"],
  sources: ["world/bbc_world:mainstream", "gdelt/reuters.com:wire"],
  articles: ["https://example.test/a"],
  affected_entities: [{ name: "Exxon", ticker: "XOM", role: "primary" }],
  second_order_effects: [],
  key_metrics: {
    sector_chain: { laya: "energy", model: "energy", keyword: "energy", chosen: "energy" },
  },
  excerpt: "Exxon said production rose 4%. XOM guides higher on the quarter.",
  source_seen: {
    "world/bbc_world:mainstream": "2026-05-03T09:00:00+00:00",
    "gdelt/reuters.com:wire": "2026-05-03T10:30:00+00:00",
  },
  analysis_source: "model",
  model_name: "test-model",
  lat: null,
  lon: null,
  timestamp: "2026-05-03T09:00:00+00:00",
  created_at: "2026-05-03T09:01:00+00:00",
};

it("backs each ticker with the sentence that names it in the stored excerpt", () => {
  const excerpt = EVENT.excerpt ?? "";
  expect(backingSentence(excerpt, "XOM")).toBe("XOM guides higher on the quarter.");
  expect(backingSentence(excerpt, "CVX")).toBe("");
});

it("shows the headline, each source with its own time, and the sector chain in order", () => {
  const text = renderEventPage(EVENT).textContent ?? "";
  expect(text).toContain("Exxon lifts production guidance");
  expect(text).toContain("bbc_world");
  expect(text).toContain("reuters.com");
  expect(text).toContain("Sun, 03 May 2026 10:30:00 GMT");
  expect(text).toContain("XOM guides higher on the quarter.");
  expect(text).toContain("The stored excerpt does not name this symbol");
  for (const who of ["Laya", "Model", "Keyword", "Chosen"]) expect(text).toContain(who);
});

it("explains the call: the labels, the model, the heuristic verdict and the rules", () => {
  const text =
    renderEventPage({
      ...EVENT,
      score_trace: { input: 4, final: 5, steps: ["model score +4", "breaking news lifts the cap"] },
    }).textContent ?? "";
  expect(text).toContain("magnitude: high");
  expect(text).toContain("actionability: high");
  expect(text).toContain("novelty: breaking");
  expect(text).toContain("Model: test-model");
  expect(text).toContain("did not disagree on direction");
  expect(text).toContain("model score +4");
  expect(text).toContain("the rules alone give +5");
});

it("says a heuristic row has no model agreement to report", () => {
  const text =
    renderEventPage({
      ...EVENT,
      analysis_source: "heuristic",
      model_name: "",
      divergence_flag: true,
    }).textContent ?? "";
  expect(text).toContain("No model judged this row");
  expect(text).not.toContain("did not disagree");
});

it("orders corroboration by arrival and calls out a single source type", () => {
  const rows = corroboration(EVENT);
  expect(rows.map((r) => r.type)).toEqual(["mainstream", "wire"]);
  expect(rows[1].deltaMs).toBe(90 * 60_000);
  const text = renderEventPage(EVENT).textContent ?? "";
  expect(text).toContain("first report");
  expect(text).toContain("+1h 30m after the first");
  expect(text).toContain("2 independent source types confirmed this story");
});

it("does not claim corroboration when there is one source type", () => {
  const one = {
    ...EVENT,
    sources: ["world/bbc_world:mainstream", "world/cnn:mainstream"],
    source_seen: {
      "world/bbc_world:mainstream": "2026-05-03T09:00:00+00:00",
      "world/cnn:mainstream": "2026-05-03T09:05:00+00:00",
    },
  };
  expect(renderEventPage(one).textContent).toContain("single-source story, not corroborated");
});

it("says the chain and the excerpt are missing instead of inventing them", () => {
  const older = { ...EVENT, excerpt: "", source_seen: {}, key_metrics: {} };
  expect(sectorChain(older)).toBeNull();
  const text = renderEventPage(older).textContent ?? "";
  expect(text).toContain("No article excerpt was stored for this call");
  expect(text).toContain("Chain not recorded for this row");
  expect(text).toContain("arrival time not recorded");
});

it("cites the evidence page from the Why this call block when no article exists", () => {
  const page = renderEventPage({ ...EVENT, articles: [] });
  const why = [...page.querySelectorAll("section.ev-block")].find(
    (block) => block.querySelector("h2")?.textContent === "Why this call",
  );
  expect(why).toBeTruthy();
  const cite = why?.querySelector<HTMLAnchorElement>("a.cite");
  expect(cite).not.toBeNull();
  expect(cite?.getAttribute("href")).toBe("/app/event/7");
});
