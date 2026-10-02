// Typed REST client. Shapes mirror the FastAPI contract in server/schemas.py.

export type Verdict = "INVEST" | "OBSERVE" | "CAUTIOUS" | "PULL_OUT";

export interface AffectedEntity {
  name: string;
  ticker?: string;
  role?: string;
  impact?: string;
}

export interface EventOut {
  id: number;
  subject: string;
  event_type: string;
  verdict: string;
  impact_direction: string;
  signal_score: number;
  confidence: number;
  reasoning: string;
  magnitude: string;
  novelty: string;
  actionability: string;
  sector_impact: string;
  sector?: string;
  tickers: string[];
  sources: string[];
  articles: string[];
  affected_entities: AffectedEntity[];
  second_order_effects: string[];
  key_metrics: Record<string, unknown>;
  lat: number | null;
  lon: number | null;
  timestamp: string | null;
  created_at: string;
}

export interface DashboardStats {
  total_events: number;
  by_verdict: Record<string, number>;
  last_update: string | null;
}

export interface DateCount {
  day: string;
  count: number;
}

export interface Sector {
  sector: string;
  event_count: number;
  avg_score: number;
  bull_bear_ratio: number;
  top_tickers: string[];
  last_event: { subject: string; created_at: string | null } | null;
}

export interface Storyline {
  member_ids: number[];
  size: number;
  tickers: string[];
  sources: string[];
  avg_score: number;
  first_seen: string | null;
  top_subject: string;
  members: EventOut[];
}

/** One leg of a scenario's net exposure: a sector or a ticker, and which way. */
export interface ScenarioLeg {
  name: string;
  direction: "up" | "down";
  strength: number; // 0..1, relative to the strongest leg
  tilt: number;
}

export interface Scenario {
  id: string;
  title: string;
  size: number;
  /** Distinct reports behind it — corroboration, which `size` cannot show. */
  reports: number;
  /** Probability the scenario's own call lands — never below 0.5. */
  probability: number;
  direction: "up" | "down" | "flat";
  stance: "risk-on" | "risk-off" | "mixed";
  tilt: number;
  data_tier: string;
  /** Scored outcomes behind `data_tier`. */
  sample_size: number;
  divergent_members: number;
  sectors: ScenarioLeg[];
  exposure: ScenarioLeg[];
  chain: string[];
  advice: string;
  member_ids: number[];
  sources: string[];
  first_seen: string | null;
}

export interface SourceHealth {
  source: string;
  status: string;
  fetched_at: string | null;
  record_count: number;
}

export interface HealthResponse {
  status: string;
  db: boolean;
  llm: boolean;
  sources: SourceHealth[];
}

export interface Correlation {
  signal_type: string;
  confidence: number;
  payload: Record<string, unknown>;
  detected_at: string;
}

export interface RssItem {
  title: string;
  link: string;
  published: string;
}

export interface FeedInfo {
  key: string;
  name: string;
  tier: string;
  region: string;
}

export interface MarketTicker {
  ticker: string;
  mentions: number;
  avg_score: number;
}

export interface Accuracy {
  total: number;
  scored: number;
  hits: number;
  hit_rate: number;
  by_verdict: Record<string, { hits: number; total: number; hit_rate: number }>;
  equity_curve: number[];
}

export interface AIAnalysis {
  summary: string;
  ticker_impacts: Array<{ ticker: string; direction: string; estimated_pct: string; reason: string }>;
  verdict_reason: string;
  /** No model answered; the text is the stored-signal summary. */
  heuristic?: boolean;
  /** A backup job is analysing on another host; ask again shortly. */
  pending?: boolean;
}

export interface EventQuery {
  limit?: number;
  offset?: number;
  date?: string;
  verdict?: string;
  ticker?: string;
  source?: string;
  event_type?: string;
  sort?: string;
  dir?: string;
}

export interface Sentiment {
  ticker: string;
  sentiment_score: number;
  bullish_count: number;
  bearish_count: number;
  neutral_count: number;
  total_posts: number;
  bullish_pct: number;
  volume_spike: boolean;
  platforms: string[];
  top_posts: { text: string; author: string; platform: string; url: string }[];
}

export interface Suggestion {
  ticker: string;
  score: number;
  mentions: number;
  momentum?: number | null;
  avg_score: number;
  avg_confidence: number;
  trust: number;
  latest_subject: string | null;
  latest_verdict: string | null;
  sector: string | null;
  last_seen: string | null;
}

export interface Quote {
  symbol: string;
  price: number | null;
  change_pct: number | null;
  name?: string | null;
  currency?: string | null;
  source: string;
}

export interface Candle {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface AgentAnalysis {
  ticker: string;
  trade_date: string;
  signal: string;
  decision: string;
  duration_seconds: number;
  errors: string[];
}

export interface Prediction {
  p_positive_move: number;
  p_verdict_correct: number;
  expected_direction: string;
  confidence_band: number;
  structural_prior: number;
  empirical_share: number;
  data_tier: string;
  factors: Record<string, number | null>;
  reliability_tables: {
    global_hit_rate: number | null;
    total_weight: number;
    sample_size: number;
    by_verdict: Record<string, { hit_rate: number | null; weight: number }>;
    by_source: Record<string, { hit_rate: number | null; weight: number }>;
  };
  event: { id: number; subject: string; verdict: string; signal_score: number; ticker?: string };
}

export interface Reliability {
  reliability: {
    global_hit_rate: number | null;
    total_weight: number;
    sample_size: number;
    by_verdict: Record<string, { hit_rate: number | null; weight: number }>;
    by_source: Record<string, { hit_rate: number | null; weight: number }>;
    by_confidence: Record<string, { hit_rate: number | null; weight: number }>;
  };
  brier: { brier: number | null; n: number };
}


// Empty = same-origin (dev proxy / nginx). Set VITE_API_BASE for split hosting.
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(API_BASE + path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  events: (q: EventQuery = {}) =>
    getJSON<{ events: EventOut[] }>(`/api/events${qs(q as Record<string, unknown>)}`).then(
      (r) => r.events,
    ),
  stats: () => getJSON<DashboardStats>("/api/stats"),
  dates: () => getJSON<{ dates: DateCount[] }>("/api/dates").then((r) => r.dates),
  sectors: () => getJSON<{ sectors: Sector[] }>("/api/sectors").then((r) => r.sectors),
  storylines: () =>
    getJSON<{ storylines: Storyline[] }>("/api/storylines").then((r) => r.storylines),
  scenarios: (limit = 6) =>
    getJSON<{ scenarios: Scenario[] }>(`/api/scenarios${qs({ limit })}`).then(
      (r) => r.scenarios,
    ),
  correlations: (date?: string) =>
    getJSON<{ correlations: Correlation[] }>(`/api/correlations${qs({ date })}`).then(
      (r) => r.correlations,
    ),
  health: () => getJSON<HealthResponse>("/api/health"),
  analyze: (id: number) => getJSON<AIAnalysis>(`/api/ai/analyze${qs({ id })}`),
  suggestions: (limit = 10) =>
    getJSON<{ suggestions: Suggestion[] }>(`/api/suggestions${qs({ limit })}`).then(
      (r) => r.suggestions,
    ),
  quotes: (symbols: string[]) =>
    getJSON<{ quotes: Quote[] }>(`/api/quotes${qs({ symbols: symbols.join(",") })}`).then(
      (r) => r.quotes,
    ),
  markets: (limit = 20) =>
    getJSON<{ tickers: MarketTicker[] }>(`/api/markets${qs({ limit })}`).then((r) => r.tickers),
  feeds: () => getJSON<{ feeds: FeedInfo[] }>("/api/feeds").then((r) => r.feeds),
  rss: (feed: string, limit = 20) =>
    getJSON<{ feed: string; name: string; tier: string; items: RssItem[] }>(
      `/api/rss-proxy${qs({ feed, limit })}`,
    ),
  accuracy: () => getJSON<Accuracy>("/api/accuracy"),
  sentiment: (ticker: string) => getJSON<Sentiment>(`/api/sentiment${qs({ ticker })}`),
  candles: (symbol: string, period = "1mo", interval = "1d") =>
    getJSON<{ symbol: string; candles: Candle[] }>(
      `/api/candles${qs({ symbol, period, interval })}`,
    ),
  agentAnalyze: (ticker: string, analysts = "market,news", debate_rounds = 1) =>
    getJSON<AgentAnalysis>(
      `/api/agents/analyze${qs({ ticker, analysts, debate_rounds })}`,
    ),
  predict: (id: number) => getJSON<Prediction>(`/api/predict/${id}`),
  reliability: () => getJSON<Reliability>("/api/reliability"),
};

export const VERDICT_COLOR: Record<string, string> = {
  INVEST: "#16c784",
  OBSERVE: "#3b82f6",
  CAUTIOUS: "#f5a623",
  PULL_OUT: "#ea3943",
};

export function verdictColor(verdict: string): string {
  return VERDICT_COLOR[verdict] ?? "#8a8f98";
}
