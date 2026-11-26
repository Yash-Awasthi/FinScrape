// MarketPanel: the live cross-asset tape.
//
// Prices come from /api/market/quotes (one batched intraday download, cached 60 s
// server-side). The panel is refreshed by the dashboard's 60 s timer while visible;
// every tile is clickable through to the chart, so the tape is a starting point for
// a ticker, not a dead end.

import { chart } from "../components/chart";
import { api, type Quote } from "../api";
import { formatMetric, type Metric } from "../format";
import { escapeHtml } from "../util";
import { Panel } from "./panel";
import { signColor } from "./viz";

const LABELS: Record<string, string> = {
  "^GSPC": "S&P 500",
  "^IXIC": "Nasdaq",
  "^DJI": "Dow",
  "^RUT": "Russell 2000",
  "^VIX": "VIX",
  "^TNX": "US 10Y",
  "CL=F": "Crude",
  "GC=F": "Gold",
  "BTC-USD": "Bitcoin",
  "EURUSD=X": "EUR/USD",
};

const metricFor = (symbol: string): Metric => {
  if (symbol.endsWith("=X")) return "fx";
  if (symbol === "^TNX") return "percent";
  if (symbol.startsWith("^")) return "points";
  return "price";
};

// The unit word a reader sees in the tile's tooltip, named in full.
const unitFor = (symbol: string, label: string): string => {
  const metric = metricFor(symbol);
  if (metric === "fx") return label;
  if (metric === "percent") return "%";
  if (metric === "points") return "points";
  return "USD";
};

export class MarketPanel extends Panel {
  constructor() {
    super({ id: "market", title: "Live market", w: 12, h: 4 });
    this.el.addEventListener("click", (e) => {
      const symbol = (e.target as HTMLElement).closest<HTMLElement>("[data-symbol]")?.dataset
        .symbol;
      if (symbol) {
        window.dispatchEvent(new CustomEvent("worldfin:select-symbol", { detail: symbol }));
      }
    });
  }

  async load(): Promise<void> {
    try {
      const response = await api.quotes();
      this.render(response.quotes, response.as_of);
    } catch {
      if (!this.quotes.length) {
        this.setContent('<p class="empty">Market data unavailable — retrying shortly.</p>');
      }
    }
  }

  private quotes: Quote[] = [];

  private render(quotes: Quote[], asOf: string): void {
    this.quotes = quotes;
    if (!quotes.length) {
      this.setContent(
        '<p class="empty">No quotes resolved. The market feed may be closed or delayed.</p>',
      );
      return;
    }
    const tiles = quotes
      .map((q) => {
        const color = signColor(q.change_percent);
        const arrow = q.change_percent > 0 ? "▲" : q.change_percent < 0 ? "▼" : "•";
        const label = LABELS[q.symbol] ?? q.symbol;
        const unit = unitFor(q.symbol, label);
        return (
          `<button class="mkt-tile" data-symbol="${escapeHtml(q.symbol)}" ` +
          `title="${escapeHtml(label)} — open chart">` +
          `<span class="mkt-label">${escapeHtml(label)}</span>` +
          `<span class="mkt-price num" title="${escapeHtml(label)} in ${escapeHtml(unit)}">` +
          `${formatMetric(metricFor(q.symbol), q.price)}</span>` +
          `<span class="mkt-change num" style="color:${color}">${arrow} ${formatMetric("change", q.change_percent)}</span>` +
          chart({
            values: q.spark,
            label: `${label} intraday price`,
            decimals: 2,
            fromZero: false,
            stroke: color,
            width: 150,
            height: 56,
          }) +
          `</button>`
        );
      })
      .join("");
    const time = new Date(asOf).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    this.setContent(
      `<div class="mkt-tape">${tiles}</div>` +
        `<p class="muted mkt-meta">Delayed intraday data · updated ${escapeHtml(time)} · ` +
        `click a tile to chart it</p>`,
    );
  }
}
