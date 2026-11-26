// Static server + hand-written JSON fixtures for the FinScrape dashboard capture.
//
// No FastAPI/Postgres is available in this environment, so this serves the real built
// SPA from web/dist and answers the REST calls it makes with fixtures shaped by
// web/src/api.ts (the contract) rather than hand-drawn HTML. Numbers are plausible;
// every panel is meant to render with data so the screenshots show the real layout.
//
//   node docs/ui/serve.cjs            # 127.0.0.1:8099
//   node docs/ui/capture.cjs          # starts this in-process and shoots PNGs
"use strict";

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "../../web/dist");
const HOST = "127.0.0.1";
const PORT = Number(process.env.CAPTURE_PORT || 8099);

// Fixture clocks are relative to the capture run, so "time ago" labels read like a
// live tape instead of depending on the wall clock of whoever opens the folder.
const NOW = Date.now();
const at = (minutesAgo) => new Date(NOW - minutesAgo * 60_000).toISOString();
const agoDays = (days) => new Date(NOW - days * 86_400_000).toISOString();

// --- fixtures ---------------------------------------------------------------

function event(o) {
  return {
    id: 0,
    subject: "",
    event_type: "geopolitical",
    verdict: "OBSERVE",
    impact_direction: "neutral",
    signal_score: 0,
    confidence: 0.6,
    reasoning: "",
    magnitude: "medium",
    novelty: "medium",
    actionability: "medium",
    divergence_flag: false,
    sector_impact: "other",
    sector: "other",
    topics: [],
    tickers: [],
    sources: ["reuters"],
    articles: [],
    affected_entities: [],
    second_order_effects: [],
    key_metrics: {},
    analysis_source: "model",
    model_name: "gpt-4o-mini",
    excerpt: "",
    source_seen: {},
    lat: null,
    lon: null,
    timestamp: at(60),
    created_at: at(60),
    ...o,
  };
}

const EVENTS = [
  event({
    id: 1,
    subject: "OPEC+ extends 1.2 mb/d cut through Q1; rerouted barrels lift tanker rates",
    event_type: "energy",
    verdict: "INVEST",
    impact_direction: "positive",
    signal_score: 62,
    confidence: 0.84,
    reasoning:
      "A supply cut held into the winter heating season tightens crude balances while hulls reroute around the Red Sea. Integrated majors gain on the flat price and tanker owners on tonne-miles; refiners with spot feedstock lose.",
    magnitude: "high",
    novelty: "medium",
    actionability: "high",
    sector_impact: "energy",
    sector: "energy",
    topics: ["energy", "shipping"],
    tickers: ["XOM", "CVX", "FRO", "VLO"],
    sources: ["reuters", "bloomberg", "eia"],
    articles: ["https://example.com/opec-extension"],
    affected_entities: [
      { name: "Exxon Mobil", ticker: "XOM", role: "producer", impact: "up" },
      { name: "Frontline", ticker: "FRO", role: "tanker owner", impact: "up" },
      { name: "Valero", ticker: "VLO", role: "refiner", impact: "down" },
    ],
    second_order_effects: [
      "Diesel cracks widen as refiners pay up for non-OPEC feedstock",
      "Asian importers pull forward cargoes before the December quota window",
    ],
    key_metrics: {
      cut_mbpd: 1.2,
      brent_curve: "backwardation",
      vlcc_day_rate_usd: 68400,
      sector_chain: { laya: "energy", model: "energy", keyword: "oil", chosen: "energy" },
    },
    excerpt:
      "OPEC+ said the 1.2 million barrel a day reduction will run through the first quarter. Frontline booked VLCC cargoes at $68,400 a day, up 31% on the month, as barrels rerouted around the Red Sea.",
    source_seen: {
      reuters: at(8),
      bloomberg: at(7),
      eia: at(5),
    },
    lat: 24.47,
    lon: 54.37,
    timestamp: at(8),
    created_at: at(2),
  }),
  event({
    id: 2,
    subject: "Chip export controls tighten on advanced nodes; suppliers guide lower",
    event_type: "policy",
    verdict: "CAUTIOUS",
    impact_direction: "negative",
    signal_score: -34,
    confidence: 0.77,
    reasoning:
      "New licensing covers sub-7nm tooling and high-bandwidth memory. The rule trims 2027 supplier revenue without closing the door on mature-node sales; hardware names with China exposure take the hit first.",
    magnitude: "high",
    novelty: "high",
    actionability: "medium",
    sector_impact: "tech",
    sector: "tech",
    topics: ["sanctions"],
    tickers: ["NVDA", "ASML", "AAPL", "MSFT"],
    sources: ["reuters", "ap", "sec_edgar"],
    articles: ["https://example.com/export-controls"],
    affected_entities: [
      { name: "ASML", ticker: "ASML", role: "tool supplier", impact: "down" },
      { name: "NVIDIA", ticker: "NVDA", role: "accelerator vendor", impact: "down" },
      { name: "Apple", ticker: "AAPL", role: "device maker", impact: "neutral" },
    ],
    second_order_effects: [
      "Memory makers redirect HBM capacity to non-China hyperscalers",
      "Mature-node foundries pick up orders priced out of the leading edge",
    ],
    key_metrics: { node_threshold_nm: 7, affected_revenue_pct: 11, licence_review_days: 45 },
    excerpt:
      "The commerce department added sub-7nm tooling and high-bandwidth memory to the licence list. ASML said the rule covers about 11% of its order book; NVIDIA guided the next quarter below consensus.",
    source_seen: {
      reuters: at(95),
      ap: at(88),
      sec_edgar: at(70),
    },
    lat: 52.37,
    lon: 4.9,
    timestamp: at(95),
    created_at: at(68),
  }),
  event({
    id: 3,
    subject: "ECB holds and signals a June cut as core CPI cools to 2.4%",
    event_type: "monetary",
    verdict: "OBSERVE",
    impact_direction: "positive",
    signal_score: 18,
    confidence: 0.71,
    divergence_flag: true,
    reasoning:
      "The hold was expected; the guidance change was not. Duration gets a bid but the euro stays soft, and the text and the model disagree on whether banks or bunds lead the move.",
    magnitude: "medium",
    novelty: "medium",
    actionability: "medium",
    sector_impact: "rates",
    sector: "rates",
    topics: ["monetary"],
    tickers: ["TLT", "IEF", "EUFN"],
    sources: ["reuters", "bloomberg", "fred"],
    articles: ["https://example.com/ecb-hold"],
    affected_entities: [
      { name: "iShares 20+ Treasury", ticker: "TLT", role: "duration proxy", impact: "up" },
      { name: "Euro banks basket", ticker: "EUFN", role: "financials", impact: "down" },
    ],
    second_order_effects: ["Southern periphery spreads grind tighter"],
    key_metrics: { core_cpi_pct: 2.4, deposit_rate_pct: 2.0, next_meeting: "2027-06-10" },
    excerpt:
      "Core inflation cooled to 2.4% from 2.7%, and the statement dropped its reference to restrictive policy. Lagarde said the June meeting is live; bunds rallied while bank shares slipped.",
    source_seen: {
      reuters: at(1200),
      bloomberg: at(1186),
      fred: at(1160),
    },
    lat: 50.11,
    lon: 8.68,
    timestamp: at(1200),
    created_at: at(1157),
  }),
  event({
    id: 4,
    subject: "Red Sea transits fall 40% after insurers withdraw war-risk cover",
    event_type: "conflict",
    verdict: "CAUTIOUS",
    impact_direction: "negative",
    signal_score: -41,
    confidence: 0.8,
    reasoning:
      "Without cover, owners refuse the southern route. Longer voyages absorb effective tonnage, which supports freight but raises landed costs for importers and squeezes just-in-time supply chains.",
    magnitude: "high",
    novelty: "medium",
    actionability: "high",
    sector_impact: "shipping",
    sector: "shipping",
    topics: ["shipping", "conflict"],
    tickers: ["FRO", "ZIM", "XOM"],
    sources: ["reuters", "ap", "acled"],
    articles: ["https://example.com/red-sea-cover"],
    affected_entities: [
      { name: "Frontline", ticker: "FRO", role: "tanker owner", impact: "up" },
      { name: "ZIM Integrated Shipping", ticker: "ZIM", role: "container line", impact: "down" },
    ],
    second_order_effects: [
      "Container spot rates on Asia-Europe jump for a third week",
      "European refiners book West African crude at a discount",
    ],
    key_metrics: { transit_drop_pct: 40, war_risk_premium_pct: 1.8, reroute_days: 11 },
    excerpt:
      "Two Lloyd's syndicates withdrew war-risk cover for the Bab el-Mandeb, and daily transits fell 40% in a week. ZIM rerouted eight services around the Cape; Frontline's VLCC rates rose again.",
    source_seen: {
      reuters: at(1560),
      ap: at(1554),
      acled: at(1533),
    },
    lat: 12.58,
    lon: 43.33,
    timestamp: at(1560),
    created_at: at(1531),
  }),
  event({
    id: 5,
    subject: "Lithium spot collapses as Chinese refiners release stockpiles",
    event_type: "commodity",
    verdict: "PULL_OUT",
    impact_direction: "negative",
    signal_score: -58,
    confidence: 0.86,
    reasoning:
      "State-linked refiners sold down inventory into a soft EV quarter. Spot carbonate broke the cash-cost floor for high-cost producers, so marginal supply shuts and equity risk concentrates in leveraged miners.",
    magnitude: "high",
    novelty: "high",
    actionability: "high",
    sector_impact: "materials",
    sector: "materials",
    topics: ["energy"],
    tickers: ["ALB", "SQM", "LIT"],
    sources: ["reuters", "bloomberg"],
    articles: ["https://example.com/lithium-spot"],
    affected_entities: [
      { name: "Albemarle", ticker: "ALB", role: "producer", impact: "down" },
      { name: "SQM", ticker: "SQM", role: "producer", impact: "down" },
    ],
    second_order_effects: ["Battery cell makers renegotiate 2027 contracts lower"],
    key_metrics: { carbonate_cny_t: 71200, drawdown_pct: 34, cash_cost_cny_t: 78000 },
    excerpt:
      "Lithium carbonate fell to 71,200 yuan a tonne after two refiners released bonded stock. That is below the 78,000 yuan cash cost of the marginal lepidolite producer, and Albemarle shares fell 9%.",
    source_seen: { reuters: at(2400), bloomberg: at(2370) },
    lat: 30.59,
    lon: 114.31,
    timestamp: at(2400),
    created_at: at(2366),
  }),
  event({
    id: 6,
    subject: "US–China tariff truce extends 90 days; ag exporters rally",
    event_type: "trade",
    verdict: "INVEST",
    impact_direction: "positive",
    signal_score: 45,
    confidence: 0.74,
    reasoning:
      "The rollover removes the January cliff for farm goods and consumer electronics. Exporters with locked contracts gain most; the option value sits in a longer deal, which the text does not promise.",
    magnitude: "medium",
    novelty: "medium",
    actionability: "medium",
    sector_impact: "agriculture",
    sector: "agriculture",
    topics: ["sanctions"],
    tickers: ["ADM", "DE", "AAPL"],
    sources: ["reuters", "ap"],
    articles: ["https://example.com/tariff-truce"],
    affected_entities: [
      { name: "Archer-Daniels-Midland", ticker: "ADM", role: "exporter", impact: "up" },
      { name: "Deere", ticker: "DE", role: "farm equipment", impact: "up" },
    ],
    second_order_effects: ["Pacific freight bookings firm for Q1"],
    key_metrics: { truce_days: 90, tariff_lines: 312, soy_volume_mt: 12_000_000 },
    excerpt:
      "The two sides rolled the truce to March and left 312 tariff lines untouched. ADM said Chinese buyers booked 12 million tonnes of soybeans for the first quarter, the largest forward book since 2024.",
    source_seen: { reuters: at(3120), ap: at(3093) },
    lat: 38.9,
    lon: -77.04,
    timestamp: at(3120),
    created_at: at(3088),
  }),
  event({
    id: 7,
    subject: "Drought cuts Argentine soy crush; meal futures invert",
    event_type: "weather",
    verdict: "OBSERVE",
    impact_direction: "positive",
    signal_score: 22,
    confidence: 0.66,
    reasoning:
      "A dry November trims the crush by an estimated 8%. Meal futures flipped into backwardation but the exporters most exposed also carry crush margin risk, so the trade is relative rather than outright.",
    magnitude: "medium",
    novelty: "medium",
    actionability: "low",
    sector_impact: "agriculture",
    sector: "agriculture",
    topics: ["livestock"],
    tickers: ["ADM", "SOYB"],
    sources: ["reuters", "usda"],
    articles: ["https://example.com/argentina-drought"],
    affected_entities: [{ name: "ADM", ticker: "ADM", role: "crusher", impact: "up" }],
    second_order_effects: ["European feed buyers substitute sunflower meal"],
    key_metrics: { crush_cut_pct: 8, rainfall_mm: 14, normal_mm: 78 },
    excerpt:
      "Rosario exchange cut its soy crush forecast by 8% after 14mm of rain against a 78mm normal. Soymeal futures inverted for the first time since August.",
    source_seen: { reuters: at(4200), usda: at(4155) },
    lat: -32.95,
    lon: -60.65,
    timestamp: at(4200),
    created_at: at(4152),
  }),
  event({
    id: 8,
    subject: "Election surprise in Ankara rattles the lira; energy importers hedge",
    event_type: "election",
    verdict: "CAUTIOUS",
    impact_direction: "negative",
    signal_score: -29,
    confidence: 0.69,
    reasoning:
      "An opposition sweep removes the policy anchor the market priced. The lira gap widens, importers of energy hedge hard, and the sovereign curve steepens before any cabinet is named.",
    magnitude: "high",
    novelty: "high",
    actionability: "medium",
    sector_impact: "financials",
    sector: "financials",
    topics: ["elections", "energy"],
    tickers: ["EEM", "TUR"],
    sources: ["reuters", "ap"],
    articles: ["https://example.com/ankara-election"],
    affected_entities: [
      { name: "iShares MSCI Turkey", ticker: "TUR", role: "country fund", impact: "down" },
      { name: "iShares MSCI EM", ticker: "EEM", role: "broad EM", impact: "down" },
    ],
    second_order_effects: ["Mediterranean gas contracts reprice on counterparty risk"],
    key_metrics: { lira_gap_pct: 7.4, turnout_pct: 86, cabinet_due_days: 12 },
    excerpt:
      "The opposition took 54% of the vote. The lira opened 7.4% weaker offshore, and the 10-year yield rose 210bp before the central bank called an emergency meeting.",
    source_seen: { reuters: at(4740), ap: at(4705) },
    lat: 39.93,
    lon: 32.86,
    timestamp: at(4740),
    created_at: at(4701),
  }),
  event({
    id: 9,
    subject: "Baltic Dry tops 2,400 as iron-ore restocking meets a thin capesize orderbook",
    event_type: "shipping",
    verdict: "INVEST",
    impact_direction: "positive",
    signal_score: 38,
    confidence: 0.72,
    reasoning:
      "Chinese steel mills restocked ahead of winter cuts into the smallest capesize orderbook in six years. Freight is the bottleneck, so owners capture the rent rather than the miners.",
    magnitude: "medium",
    novelty: "low",
    actionability: "medium",
    sector_impact: "shipping",
    sector: "shipping",
    topics: ["shipping"],
    tickers: ["FRO", "ZIM", "BDRY"],
    sources: ["reuters", "bloomberg"],
    articles: ["https://example.com/baltic-dry"],
    affected_entities: [{ name: "Frontline", ticker: "FRO", role: "owner", impact: "up" }],
    second_order_effects: [],
    key_metrics: { bdi: 2418, capesize_day_rate_usd: 31200, orderbook_pct_fleet: 4.1 },
    excerpt:
      "The Baltic Dry Index closed at 2,418, its highest since March. Capesize spot rates reached $31,200 a day with the orderbook at 4.1% of the fleet.",
    source_seen: { reuters: at(5700), bloomberg: at(5665) },
    lat: 31.23,
    lon: 121.47,
    timestamp: at(5700),
    created_at: at(5662),
  }),
];

const byId = new Map(EVENTS.map((e) => [e.id, e]));

const STATS = {
  total_events: 9842,
  by_verdict: { INVEST: 2814, OBSERVE: 3902, CAUTIOUS: 2210, PULL_OUT: 916 },
  last_update: at(2),
  ingest_interval_minutes: 15,
};

const DATES = (() => {
  const counts = [31, 28, 12, 9, 34, 41, 38, 26, 14, 11, 39, 44, 47, 22];
  return counts.map((count, i) => ({
    day: new Date(NOW - (13 - i) * 86_400_000).toISOString().slice(0, 10),
    count,
  }));
})();

const SECTORS = [
  {
    sector: "energy",
    event_count: 4,
    avg_score: 1.84,
    bull_bear_ratio: 2.6,
    top_tickers: ["XOM", "CVX", "FRO"],
    last_event: {
      subject: "OPEC+ extends 1.2 mb/d cut through Q1",
      created_at: at(2),
    },
  },
  {
    sector: "shipping",
    event_count: 3,
    avg_score: 0.42,
    bull_bear_ratio: 1.4,
    top_tickers: ["FRO", "ZIM", "BDRY"],
    last_event: { subject: "Baltic Dry tops 2,400", created_at: at(5662) },
  },
  {
    sector: "tech",
    event_count: 2,
    avg_score: -1.35,
    bull_bear_ratio: 0.5,
    top_tickers: ["NVDA", "ASML", "AAPL"],
    last_event: { subject: "Chip export controls tighten", created_at: at(68) },
  },
  {
    sector: "rates",
    event_count: 2,
    avg_score: 0.88,
    bull_bear_ratio: 1.8,
    top_tickers: ["TLT", "IEF"],
    last_event: { subject: "ECB holds and signals a June cut", created_at: at(1157) },
  },
  {
    sector: "agriculture",
    event_count: 2,
    avg_score: 1.12,
    bull_bear_ratio: 3.0,
    top_tickers: ["ADM", "DE", "SOYB"],
    last_event: {
      subject: "Drought cuts Argentine soy crush",
      created_at: at(4152),
    },
  },
  {
    sector: "materials",
    event_count: 1,
    avg_score: -2.4,
    bull_bear_ratio: 0.2,
    top_tickers: ["ALB", "SQM"],
    last_event: {
      subject: "Lithium spot collapses as refiners release stockpiles",
      created_at: at(2366),
    },
  },
  {
    sector: "financials",
    event_count: 1,
    avg_score: -1.1,
    bull_bear_ratio: 0.5,
    top_tickers: ["EEM", "TUR"],
    last_event: {
      subject: "Election surprise in Ankara rattles the lira",
      created_at: at(4701),
    },
  },
  {
    sector: "defense",
    event_count: 1,
    avg_score: 1.6,
    bull_bear_ratio: 4.0,
    top_tickers: ["LMT", "RTX"],
    last_event: { subject: "Naval escort mandate widens", created_at: at(2880) },
  },
];

const WATCHLIST = {
  id: 1,
  name: "My Desk",
  created_at: agoDays(16),
  items: [
    { id: 1, kind: "sector", value: "energy" },
    { id: 2, kind: "ticker", value: "XOM" },
    { id: 3, kind: "topic", value: "shipping" },
    { id: 4, kind: "ticker", value: "NVDA" },
  ],
};

const STORYLINES = [
  {
    member_ids: [1, 4],
    size: 2,
    tickers: ["FRO", "XOM", "ZIM"],
    sources: ["reuters", "ap", "bloomberg", "acled"],
    avg_score: 0.5,
    first_seen: at(1560),
    top_subject: "OPEC+ extends 1.2 mb/d cut through Q1; rerouted barrels lift tanker rates",
    members: [byId.get(1), byId.get(4)],
  },
  {
    member_ids: [7, 9],
    size: 2,
    tickers: ["ADM", "FRO"],
    sources: ["reuters", "usda", "bloomberg"],
    avg_score: 1.2,
    first_seen: at(5700),
    top_subject: "Baltic Dry tops 2,400 as iron-ore restocking meets a thin capesize orderbook",
    members: [byId.get(9), byId.get(7)],
  },
];

const SCENARIOS = [
  {
    id: "s1",
    title: "Energy squeeze into winter",
    size: 3,
    reports: 6,
    probability: 0.71,
    ci95: [0.62, 0.79],
    n_members: 3,
    direction: "up",
    stance: "risk-off",
    tilt: 0.42,
    data_tier: "empirical",
    sample_size: 34,
    divergent_members: 1,
    sectors: [
      { name: "energy", direction: "up", strength: 1, tilt: 0.62 },
      { name: "shipping", direction: "up", strength: 0.71, tilt: 0.34 },
      { name: "consumer", direction: "down", strength: 0.35, tilt: -0.18 },
    ],
    exposure: [
      { name: "XOM", direction: "up", strength: 1, tilt: 0.58 },
      { name: "FRO", direction: "up", strength: 0.82, tilt: 0.47 },
      { name: "CVX", direction: "up", strength: 0.64, tilt: 0.31 },
    ],
    chain: [
      "Supply cut holds through the heating season",
      "Hulls reroute, tonne-miles absorb capacity",
      "Freight and crude rise together; importers pay",
    ],
    advice:
      "Energy and tanker exposure carries the trade; keep the position small because one member disagrees on duration.",
    member_ids: [1, 4, 9],
    sources: ["reuters", "bloomberg", "eia", "acled"],
    first_seen: at(5700),
  },
  {
    id: "s2",
    title: "Export controls bite the leading edge",
    size: 2,
    reports: 4,
    probability: 0.58,
    ci95: [0.47, 0.68],
    n_members: 2,
    direction: "down",
    stance: "risk-off",
    tilt: -0.28,
    data_tier: "thin-data",
    sample_size: 12,
    divergent_members: 0,
    sectors: [
      { name: "tech", direction: "down", strength: 1, tilt: -0.44 },
      { name: "materials", direction: "down", strength: 0.52, tilt: -0.21 },
    ],
    exposure: [
      { name: "NVDA", direction: "down", strength: 1, tilt: -0.39 },
      { name: "ASML", direction: "down", strength: 0.88, tilt: -0.35 },
      { name: "AAPL", direction: "down", strength: 0.3, tilt: -0.08 },
    ],
    chain: [
      "Licences cover sub-7nm tooling and HBM",
      "Suppliers cut 2027 guidance",
      "Mature-node capacity gains relative",
    ],
    advice:
      "Underweight leading-edge suppliers; the sample behind this scenario is thin, so size it below the energy trade.",
    member_ids: [2, 5],
    sources: ["reuters", "ap", "sec_edgar"],
    first_seen: at(2366),
  },
  {
    id: "s3",
    title: "Tariff truce keeps ag exports moving",
    size: 2,
    reports: 3,
    probability: 0.64,
    ci95: [0.54, 0.73],
    n_members: 2,
    direction: "up",
    stance: "risk-on",
    tilt: 0.19,
    data_tier: "empirical",
    sample_size: 21,
    divergent_members: 1,
    sectors: [
      { name: "agriculture", direction: "up", strength: 1, tilt: 0.36 },
      { name: "industrials", direction: "up", strength: 0.48, tilt: 0.14 },
    ],
    exposure: [
      { name: "ADM", direction: "up", strength: 1, tilt: 0.33 },
      { name: "DE", direction: "up", strength: 0.61, tilt: 0.2 },
    ],
    chain: [
      "Truce rolls 312 tariff lines to March",
      "Chinese buyers book a large forward soybean book",
      "Farm equipment demand follows the export volume",
    ],
    advice:
      "Ag exporters are the cleanest expression; the truce is a rollover, not a deal, so do not pay for a permanent resolution.",
    member_ids: [6, 7],
    sources: ["reuters", "ap", "usda"],
    first_seen: at(4152),
  },
];

const ACCURACY = {
  total: 120,
  scored: 84,
  hits: 52,
  hit_rate: 0.619,
  n: 84,
  ci95: [0.51, 0.72],
  sample: "n=84, 51–72%",
  by_verdict: {
    INVEST: { hits: 24, total: 34, hit_rate: 0.706, n: 34, ci95: [0.54, 0.83], sample: "n=34, 54–83%" },
    CAUTIOUS: {
      hits: 14,
      total: 26,
      hit_rate: 0.538,
      n: 26,
      ci95: [0.36, 0.71],
      sample: "n=26, 36–71% · wide interval",
    },
    OBSERVE: { hits: 9, total: 14, hit_rate: 0.643, n: 14, ci95: [0.39, 0.84], sample: "n=14, 39–84% · wide interval" },
    PULL_OUT: { hits: 5, total: 10, hit_rate: 0.5, n: 10, ci95: [0.24, 0.76], sample: "n=10, 24–76% · wide interval" },
  },
  equity_curve: [
    1, 0, 1, 2, 1, 2, 3, 2, 3, 4, 5, 4, 5, 4, 3, 4, 5, 6, 7, 6, 7, 8, 7, 8, 9, 10, 9, 10, 11,
    10, 11, 12, 11, 12, 13, 12, 13, 14, 15, 14, 15, 16,
  ],
  equity_metrics: { sharpe_ratio: 1.14, sortino_ratio: 1.62, max_drawdown: 0.087 },
  vs_spy: {
    d2: {
      scored: 76,
      hits: 44,
      hit_rate: 0.579,
      n: 76,
      ci95: [0.47, 0.68],
      sample: "n=76, 47–68%",
      by_verdict: {
        INVEST: { hits: 20, total: 31, hit_rate: 0.645, n: 31, ci95: [0.47, 0.79], sample: "n=31" },
        CAUTIOUS: { hits: 12, total: 24, hit_rate: 0.5, n: 24, ci95: [0.31, 0.69], sample: "n=24" },
        OBSERVE: { hits: 8, total: 12, hit_rate: 0.667, n: 12, ci95: [0.39, 0.86], sample: "n=12 · wide interval" },
        PULL_OUT: { hits: 4, total: 9, hit_rate: 0.444, n: 9, ci95: [0.19, 0.73], sample: "n=9 · wide interval" },
      },
    },
    d4: {
      scored: 68,
      hits: 41,
      hit_rate: 0.603,
      n: 68,
      ci95: [0.48, 0.71],
      sample: "n=68, 48–71%",
      by_verdict: {
        INVEST: { hits: 19, total: 28, hit_rate: 0.679, n: 28, ci95: [0.49, 0.82], sample: "n=28" },
        CAUTIOUS: { hits: 11, total: 22, hit_rate: 0.5, n: 22, ci95: [0.31, 0.69], sample: "n=22" },
        OBSERVE: { hits: 7, total: 10, hit_rate: 0.7, n: 10, ci95: [0.4, 0.89], sample: "n=10 · wide interval" },
        PULL_OUT: { hits: 4, total: 8, hit_rate: 0.5, n: 8, ci95: [0.22, 0.78], sample: "n=8 · wide interval" },
      },
    },
  },
  calibration: {
    n: 84,
    brier: 0.221,
    brier_decomposition: { reliability: 0.031, resolution: 0.044, uncertainty: 0.234 },
    base_rate: 0.58,
    reliability_curve: [
      { bucket: ".5-.6", n: 21, predicted: 0.55, realised: 0.52, gap: 0.03 },
      { bucket: ".6-.7", n: 30, predicted: 0.65, realised: 0.63, gap: 0.02 },
      { bucket: ".7-.8", n: 22, predicted: 0.75, realised: 0.77, gap: -0.02 },
      { bucket: ".8-.9", n: 11, predicted: 0.85, realised: 0.82, gap: 0.03 },
    ],
    buckets: {
      ".5-.6": { n: 21, hit_rate: 0.52, ci95: [0.32, 0.71] },
      ".6-.7": { n: 30, hit_rate: 0.63, ci95: [0.45, 0.78] },
      ".7-.8": { n: 22, hit_rate: 0.77, ci95: [0.57, 0.9] },
      ".8-.9": { n: 11, hit_rate: 0.82, ci95: [0.52, 0.95] },
    },
  },
  window: { from: agoDays(68), to: agoDays(12) },
};

const OUTCOMES = [
  [1, "OPEC+ extends 1.2 mb/d cut through Q1", "INVEST", ["XOM", "FRO"], 0, 2.8, true, 1.9, 3.4, true, true],
  [2, "Chip export controls tighten on advanced nodes", "CAUTIOUS", ["NVDA", "ASML"], 0, -3.6, true, -2.2, -4.1, true, true],
  [3, "ECB holds and signals a June cut", "OBSERVE", ["TLT"], 1, 0.4, null, 0.1, null, null, null],
  [4, "Red Sea transits fall 40%", "CAUTIOUS", ["ZIM"], 1, -5.2, true, -3.8, -6.0, true, true],
  [5, "Lithium spot collapses", "PULL_OUT", ["ALB", "SQM"], 2, -7.1, true, -5.4, -8.2, true, true],
  [6, "US–China tariff truce extends 90 days", "INVEST", ["ADM", "DE"], 2, 1.4, true, 0.6, 1.1, true, false],
  [7, "Drought cuts Argentine soy crush", "OBSERVE", ["ADM"], 3, 1.1, true, 0.8, 1.3, null, true],
  [8, "Election surprise in Ankara", "CAUTIOUS", ["TUR"], 3, -6.3, true, -4.9, -7.0, true, true],
  [9, "Baltic Dry tops 2,400", "INVEST", ["FRO"], 4, 0.7, null, 0.3, null, null, null],
  [10, "Naval escort mandate widens", "INVEST", ["LMT", "RTX"], 5, 2.1, true, 1.2, 2.6, true, true],
  [11, "Copper strike at Escondida ends", "PULL_OUT", ["FCX"], 6, 2.4, false, 1.1, 2.0, false, false],
].map(([event_id, subject, verdict, tickers, daysAgo, price_move_pct, correct, ex2, ex4, correct2, correct4]) => ({
  event_id,
  subject,
  verdict,
  tickers,
  timestamp: agoDays(daysAgo),
  price_move_pct,
  correct,
  ex2,
  ex4,
  correct2,
  correct4,
}));

const SUGGESTIONS = [
  ["XOM", 8.4, 14, 0.62, 1.9, 0.81, 0.88, "OPEC+ extends 1.2 mb/d cut through Q1", "INVEST", "energy"],
  ["FRO", 7.9, 11, 0.55, 2.4, 0.79, 0.9, "Red Sea transits fall 40%", "CAUTIOUS", "shipping"],
  ["NVDA", 6.1, 9, -0.41, -1.2, 0.74, 0.86, "Chip export controls tighten", "CAUTIOUS", "tech"],
  ["ADM", 5.6, 7, 0.38, 1.4, 0.72, 0.8, "US–China tariff truce extends 90 days", "INVEST", "agriculture"],
  ["TLT", 4.8, 6, 0.11, 0.6, 0.68, 0.75, "ECB holds and signals a June cut", "OBSERVE", "rates"],
  ["ALB", 4.2, 5, -0.72, -2.8, 0.7, 0.82, "Lithium spot collapses", "PULL_OUT", "materials"],
  ["ZIM", 3.7, 4, -0.3, -0.9, 0.66, 0.71, "Red Sea transits fall 40%", "CAUTIOUS", "shipping"],
  ["DE", 3.1, 3, 0.24, 1.1, 0.64, 0.7, "US–China tariff truce extends 90 days", "INVEST", "agriculture"],
].map(([ticker, score, mentions, momentum, avg_score, avg_confidence, trust, latest_subject, latest_verdict, sector]) => ({
  ticker,
  score,
  mentions,
  momentum,
  avg_score,
  avg_confidence,
  trust,
  latest_subject,
  latest_verdict,
  sector,
  last_seen: at(8),
}));

const HEALTH = {
  status: "ok",
  db: true,
  llm: true,
  sources: [
    ["reuters", "OK", at(3), 142],
    ["ap", "OK", at(5), 118],
    ["bloomberg", "OK", at(7), 96],
    ["gdelt", "OK", at(9), 431],
    ["acled", "STALE", at(300), 22],
    ["reliefweb", "OK", at(12), 31],
    ["eia", "EMPTY", at(45), 0],
    ["fred", "OK", at(30), 64],
    ["sec_edgar", "OK", at(60), 47],
    ["usda", "OK", at(400), 18],
    ["yahoo_finance", "WARN", at(2), 210],
  ].map(([source, status, fetched_at, record_count]) => ({ source, status, fetched_at, record_count })),
};

const CORRELATIONS = [
  {
    signal_type: "convergence",
    confidence: 0.91,
    payload: { id: "OPEC+ extends 1.2 mb/d cut", value: 4.2 },
    detected_at: at(7),
  },
  {
    signal_type: "flow_drop",
    confidence: 0.84,
    payload: { id: "Bab el-Mandeb transits", value: -40.1 },
    detected_at: at(1500),
  },
  {
    signal_type: "velocity_spike",
    confidence: 0.78,
    payload: { id: "lithium carbonate", value: 3.4 },
    detected_at: at(2350),
  },
  {
    signal_type: "silent_divergence",
    confidence: 0.66,
    payload: { id: "EEM", value: 2.3 },
    detected_at: at(3600),
  },
];

const QUOTES = [
  ["^GSPC", 6412.38, 6378.11, 0.54],
  ["^IXIC", 21844.9, 21902.4, -0.26],
  ["^DJI", 46120.7, 45988.2, 0.29],
  ["^RUT", 2486.3, 2501.8, -0.62],
  ["^VIX", 15.84, 16.52, -4.12],
  ["^TNX", 4.018, 4.062, -1.08],
  ["CL=F", 78.42, 76.9, 1.98],
  ["GC=F", 2714.6, 2704.2, 0.38],
  ["BTC-USD", 96412.0, 97840.0, -1.46],
  ["EURUSD=X", 1.0872, 1.0849, 0.21],
  ["XOM", 118.34, 116.02, 2.0],
].map(([symbol, price, previous_close, change_percent]) => {
  const spark = Array.from({ length: 24 }, (_, i) => {
    const drift = (price - previous_close) * (i / 23);
    const wobble = Math.sin(i * 1.7) * price * 0.0018;
    return Number((previous_close + drift + wobble).toFixed(3));
  });
  return { symbol, price, previous_close, change_percent, spark };
});

const QUOTE_RESPONSE = {
  quotes: QUOTES,
  as_of: at(1),
  symbols: QUOTES.map((q) => q.symbol),
};

const CANDLES = (() => {
  const out = [];
  let close = 104.2;
  for (let i = 0; i < 30; i++) {
    const day = new Date(Date.UTC(2026, 9, 28 + i));
    const drift = Math.sin(i / 4) * 0.9 + 0.42;
    const open = close;
    close = Number((open + drift).toFixed(2));
    const high = Number((Math.max(open, close) + 0.7 + (i % 3) * 0.2).toFixed(2));
    const low = Number((Math.min(open, close) - 0.6 - (i % 2) * 0.25).toFixed(2));
    out.push({
      t: day.toISOString().slice(0, 10),
      o: open,
      h: high,
      l: low,
      c: close,
      v: 9_000_000 + ((i * 1_317_991) % 6_000_000),
    });
  }
  return out;
})();

const RELIABILITY = {
  reliability: {
    global_hit_rate: 0.619,
    total_weight: 58.4,
    sample_size: 84,
    by_verdict: {
      INVEST: { hit_rate: 0.706, weight: 22.4 },
      CAUTIOUS: { hit_rate: 0.538, weight: 18.1 },
      OBSERVE: { hit_rate: 0.643, weight: 11.2 },
      PULL_OUT: { hit_rate: 0.5, weight: 6.7 },
    },
    by_source: {
      reuters: { hit_rate: 0.66, weight: 26.3 },
      ap: { hit_rate: 0.61, weight: 18.9 },
      bloomberg: { hit_rate: 0.58, weight: 13.2 },
    },
    by_confidence: {
      "0.5-0.6": { hit_rate: 0.52, weight: 14.6 },
      "0.6-0.7": { hit_rate: 0.63, weight: 21.8 },
      "0.7-0.8": { hit_rate: 0.77, weight: 15.1 },
      "0.8-0.9": { hit_rate: 0.82, weight: 6.9 },
    },
  },
  brier: {
    brier: 0.221,
    n: 84,
    decomposition: { reliability: 0.031, resolution: 0.044, uncertainty: 0.234 },
    base_rate: 0.58,
  },
};

const VERDICT_BIAS = { INVEST: 0.706, CAUTIOUS: 0.538, OBSERVE: 0.643, PULL_OUT: 0.5 };

function predictionFor(id) {
  const ev = byId.get(id) || EVENTS[0];
  const p = VERDICT_BIAS[ev.verdict] ?? 0.58;
  return {
    p_positive_move: ev.verdict === "INVEST" ? 0.64 : 0.36,
    p_verdict_correct: p,
    expected_direction: ev.verdict === "INVEST" ? "up" : "down",
    confidence_band: 0.12,
    structural_prior: 0.55,
    empirical_share: 0.68,
    data_tier: "empirical",
    factors: { verdict_bias: p, source_trust: 0.62, recency: 0.71, sector_momentum: 0.48 },
    reliability_tables: {
      global_hit_rate: 0.619,
      total_weight: 58.4,
      sample_size: 84,
      by_verdict: RELIABILITY.reliability.by_verdict,
      by_source: RELIABILITY.reliability.by_source,
    },
    event: {
      id: ev.id,
      subject: ev.subject,
      verdict: ev.verdict,
      signal_score: ev.signal_score,
      ticker: ev.tickers[0],
    },
  };
}

const COUNCIL = {
  consensus_verdict: "CAUTIOUS",
  consensus_score: -18,
  agreement_level: 0.72,
  dissenting_agents: ["macro"],
  key_risks: [
    "The supply cut can be unwound early if demand softens",
    "War-risk cover may return within weeks and normalise freight",
  ],
  key_opportunities: [
    "Tanker tonne-miles stay elevated even after a partial reopening",
    "Integrated majors hedge the flat price with downstream margins",
  ],
};

const ANALYSIS = {
  summary:
    "A held supply cut plus a longer shipping route is a two-channel tightening: the flat price rises and so does the cost of moving it. Energy and tanker exposure carries the call; refiners pay the difference.",
  ticker_impacts: [
    { ticker: "XOM", direction: "up", estimated_pct: "+2.0 to +3.5%", reason: "Producer leverage to a firmer flat price" },
    { ticker: "FRO", direction: "up", estimated_pct: "+4.0 to +6.0%", reason: "VLCC day rates up 31% on the month" },
    { ticker: "VLO", direction: "down", estimated_pct: "-1.0 to -2.0%", reason: "Spot feedstock costs widen the crack" },
  ],
  verdict_reason:
    "Three independent sources carried the extension within forty minutes and the freight market confirmed it with a rate print, so the signal is corroborated rather than single-sourced.",
  heuristic: false,
  pending: false,
};

// --- routing ----------------------------------------------------------------

function json(res, body, status = 200) {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "Content-Length": Buffer.byteLength(text),
  });
  res.end(text);
}

function filteredEvents(q) {
  let rows = EVENTS;
  if (q.get("date")) rows = rows.filter((e) => (e.timestamp || "").startsWith(q.get("date")));
  if (q.get("verdict")) rows = rows.filter((e) => e.verdict === q.get("verdict"));
  if (q.get("ticker")) rows = rows.filter((e) => e.tickers.includes(q.get("ticker")));
  if (q.get("source")) rows = rows.filter((e) => e.sources.includes(q.get("source")));
  if (q.get("since_id")) rows = rows.filter((e) => e.id > Number(q.get("since_id")));
  const offset = Number(q.get("offset") || 0);
  const limit = Math.min(Number(q.get("limit") || 200), 200);
  return rows.slice(offset, offset + limit);
}

function apiResponse(pathname, q) {
  if (pathname === "/api/events") return { events: filteredEvents(q) };
  const eventMatch = /^\/api\/events\/(\d+)$/.exec(pathname);
  if (eventMatch) return byId.get(Number(eventMatch[1])) || null;
  if (pathname === "/api/stats") return STATS;
  if (pathname === "/api/dates") return { dates: DATES };
  if (pathname === "/api/sectors") return { sectors: SECTORS };
  if (pathname === "/api/watchlists") return { watchlists: [WATCHLIST] };
  if (pathname === "/api/watchlists/1/feed") {
    const ids = [1, 4, 2, 9, 7];
    return { events: ids.map((id) => byId.get(id)).filter(Boolean) };
  }
  if (pathname === "/api/storylines") return { storylines: STORYLINES };
  if (pathname === "/api/scenarios") return { scenarios: SCENARIOS };
  const scenarioMatch = /^\/api\/scenarios\/([^/]+)$/.exec(pathname);
  if (scenarioMatch) {
    const s = SCENARIOS.find((x) => x.id === decodeURIComponent(scenarioMatch[1]));
    if (!s) return null;
    return {
      scenario: s,
      members: s.member_ids.map((id) => {
        const e = byId.get(id);
        return {
          id: e.id,
          subject: e.subject,
          verdict: e.verdict,
          signal_score: e.signal_score,
          confidence: e.confidence,
          sector_impact: e.sector_impact,
          timestamp: e.timestamp,
          sources: e.sources,
        };
      }),
      history: [
        { probability: 0.64, n_members: 2, at: at(4300) },
        { probability: 0.67, n_members: 2, at: at(3000) },
        { probability: 0.69, n_members: 3, at: at(700) },
        { probability: 0.71, n_members: 3, at: at(6) },
      ],
      window: { events_considered: 240, event_cap: 400, lookback_days: 7 },
    };
  }
  if (pathname === "/api/correlations") return { correlations: CORRELATIONS };
  if (pathname === "/api/health") return HEALTH;
  if (pathname === "/api/suggestions") return { suggestions: SUGGESTIONS };
  if (pathname === "/api/accuracy") return ACCURACY;
  if (pathname === "/api/outcomes") return { outcomes: OUTCOMES };
  if (pathname === "/api/candles") return { symbol: q.get("symbol") || "XOM", candles: CANDLES };
  if (pathname === "/api/market/quotes") return QUOTE_RESPONSE;
  const predictMatch = /^\/api\/predict\/(\d+)$/.exec(pathname);
  if (predictMatch) return predictionFor(Number(predictMatch[1]));
  if (pathname === "/api/reliability") return RELIABILITY;
  if (pathname === "/api/ai/council") return COUNCIL;
  if (pathname === "/api/ai/analyze") return ANALYSIS;
  // The landing page reads this for its feed count only.
  if (pathname === "/api/feeds") {
    return { feeds: HEALTH.sources.map((s) => ({ name: s.source, status: s.status })) };
  }
  return undefined;
}

// --- static file serving ----------------------------------------------------

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".json": "application/json; charset=utf-8",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
  ".ico": "image/x-icon",
};

function serveStatic(pathname, res) {
  let rel = decodeURIComponent(pathname);
  if (rel === "/" || rel === "") rel = "/index.html";
  if (rel === "/app" || rel === "/app/") rel = "/app/index.html";
  // Detail routes are hash-only here, but accept the path form too so the SPA boots.
  if (/^\/app\/(event|scenario)\//.test(rel)) rel = "/app/index.html";
  const file = path.resolve(ROOT, "." + rel);
  if (!file.startsWith(ROOT + path.sep) && file !== path.join(ROOT, "index.html")) {
    res.writeHead(403).end("forbidden");
    return;
  }
  fs.readFile(file, (err, buf) => {
    if (err) {
      res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }).end("not found");
      return;
    }
    res.writeHead(200, {
      "Content-Type": MIME[path.extname(file).toLowerCase()] || "application/octet-stream",
      "Content-Length": buf.length,
      "Cache-Control": "no-store",
    });
    res.end(buf);
  });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${HOST}:${PORT}`);
  if (url.pathname.startsWith("/api/")) {
    const body = apiResponse(url.pathname, url.searchParams);
    if (body === undefined || body === null) return json(res, { detail: "not found" }, 404);
    return json(res, body);
  }
  return serveStatic(url.pathname, res);
});

function start(port = PORT) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, HOST, () => resolve(server));
  });
}

function stop() {
  return new Promise((resolve) => server.close(() => resolve()));
}

if (require.main === module) {
  start().then(
    () => console.log(`serving ${ROOT} on http://${HOST}:${PORT}`),
    (err) => {
      console.error(err);
      process.exit(1);
    },
  );
}

module.exports = { start, stop, server, EVENTS, SCENARIOS };
