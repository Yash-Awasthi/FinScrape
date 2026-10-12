// Product panels fed by the API. Each exposes update()/load() that fills its body.

import {
  type Accuracy,
  api,
  type Candle,
  type Correlation,
  type DashboardStats,
  type DateCount,
  type EventOut,
  type HealthResponse,
  type HitRate,
  type Outcome,
  type Prediction,
  type Scenario,
  type ScenarioLeg,
  type Sector,
  type Suggestion,
  verdictColor,
} from "../api";
import { escapeHtml, fmtPct, sourceLabel, timeAgo } from "../util";
import { VIZ_COLORS, barChart, calibration, columns, signColor, sparkline } from "./viz";
import { Panel } from "./panel";

// What each detector in server/correlate.py means, for a reader who never saw it.
const SIGNAL_MEANING: Record<string, string> = {
  convergence: "three or more source types carried this story within an hour",
  triangulation: "wire, government and intelligence sources all carried it",
  flow_drop: "a supply or flow disruption is being reported",
  velocity_spike: "coverage of this topic is over 3× its 7-day normal",
  explained_market_move: "a 2%+ price move with news that explains it",
  silent_divergence: "a 2%+ price move with no news to explain it",
  flow_price_divergence: "an energy price moved with little supply news behind it",
  prediction_leads_news: "the analysis expects a large move the news has barely covered",
};

export class CorrelationPanel extends Panel {
  constructor() {
    super({ id: "correlations", title: "Correlation signals", w: 6, h: 8 });
  }
  update(signals: Correlation[]): void {
    if (!signals.length) {
      this.setContent('<p class="empty">No correlation signals in this window.</p>');
      return;
    }
    const rows = signals
      .map((s) => {
        const id = escapeHtml(String(s.payload?.id ?? ""));
        const value = s.payload?.value;
        const meaning = SIGNAL_MEANING[s.signal_type] ?? "";
        return (
          `<li><span><b>${escapeHtml(s.signal_type.replace(/_/g, " "))}</b> · ${id}` +
          (typeof value === "number" ? ` · ${value.toFixed(1)}` : "") +
          ` <span class="muted">${Math.round(s.confidence * 100)}% · ${timeAgo(s.detected_at)} ago</span></span>` +
          (meaning ? `<span class="muted">${escapeHtml(meaning)}</span>` : "") +
          `</li>`
        );
      })
      .join("");
    this.setContent(`<ul class="corr-list">${rows}</ul>`);
  }
}

export class SectorPanel extends Panel {
  constructor() {
    super({ id: "sectors", title: "Sector heat", w: 12, h: 5 });
  }
  async load(): Promise<void> {
    try {
      this.render(await api.sectors());
    } catch {
      this.setContent('<p class="empty">Sector data unavailable.</p>');
    }
  }
  private render(sectors: Sector[]): void {
    if (!sectors.length) return this.setContent('<p class="empty">No sector signals yet.</p>');
    const maxCount = Math.max(...sectors.map((s) => s.event_count));
    const wrap = document.createElement("div");
    wrap.className = "sector-grid";
    wrap.innerHTML = sectors
      .map((s) => {
        // chip size scales with event_count; color runs green→red by avg score
        const em = (0.95 + (s.event_count / maxCount) * 0.6).toFixed(2);
        const score = s.avg_score;
        const color = score <= -2 ? "#ea3943" : score < 0 ? "#f58d3f" : score <= 2 ? "#3b82f6" : "#16c784";
        const tickers = s.top_tickers.length ? s.top_tickers.join(", ") : "—";
        const ratio = s.bull_bear_ratio == null ? "—" : `${s.bull_bear_ratio.toFixed(1)}:1`;
        return (
          `<button class="sector-chip" data-sector="${escapeHtml(s.sector)}" style="font-size:${em}em;--sector-color:${color}" ` +
          `title="${escapeHtml(s.sector)} · ${s.event_count} events · avg ${score >= 0 ? "+" : ""}${score} · bull:bear ${ratio}\nTop: ${escapeHtml(tickers)}">` +
          `<span class="sector-name">${escapeHtml(s.sector)}</span>` +
          `<span class="sector-n">${s.event_count}</span>` +
          `<span class="sector-score" style="color:${color}">${score >= 0 ? "+" : ""}${score}</span>` +
          `</button>`
        );
      })
      .join("");
    wrap.addEventListener("click", (e) => {
      const sector = (e.target as HTMLElement).closest<HTMLElement>(".sector-chip")?.dataset.sector;
      if (sector) window.dispatchEvent(new CustomEvent("worldfin:select-sector", { detail: sector }));
    });
    const chart = document.createElement("div");
    chart.innerHTML = barChart(
      sectors.slice(0, 8).map((s) => ({
        label: s.sector,
        value: s.event_count,
        color: signColor(s.avg_score),
        note: `${s.event_count} · ${s.avg_score >= 0 ? "+" : ""}${s.avg_score}`,
      })),
      "events per sector",
    );
    const box = document.createElement("div");
    box.append(wrap, chart);
    this.setContent(box);
  }
}

export class StatsPanel extends Panel {
  constructor() {
    super({ id: "stats", title: "Calls by verdict", w: 4, h: 4 });
  }
  update(stats: DashboardStats): void {
    const verdicts = Object.entries(stats.by_verdict);
    const max = Math.max(1, ...verdicts.map(([, n]) => n));
    const bars = verdicts
      .map(([verdict, n]) => {
        const color = verdictColor(verdict);
        return (
          `<div class="stat-row"><span class="stat-label">${escapeHtml(verdict)}</span>` +
          `<span class="stat-bar"><i style="width:${Math.round((n / max) * 100)}%;background:${color}"></i></span>` +
          `<span class="stat-n">${n}</span></div>`
        );
      })
      .join("");
    const updated = stats.last_update ? new Date(stats.last_update).toLocaleTimeString() : "—";
    this.setContent(
      `<div class="stat-total">${stats.total_events}<span class="muted"> events · updated ${escapeHtml(updated)}</span></div>` +
        (bars || '<p class="empty">No verdicts yet.</p>'),
    );
  }
}

export class SuggestionsPanel extends Panel {
  constructor() {
    super({ id: "suggestions", title: "Tickers in the news", w: 4, h: 8 });
    this.el.addEventListener("click", (e) => {
      const sym = (e.target as HTMLElement).closest<HTMLElement>(".sug-click")?.dataset.sym;
      if (sym) window.dispatchEvent(new CustomEvent("worldfin:select-symbol", { detail: sym }));
    });
  }
  async load(): Promise<void> {
    try {
      this.render(await api.suggestions(25));
    } catch {
      this.setContent('<p class="empty">Ticker list unavailable.</p>');
    }
  }
  private render(sugs: Suggestion[]): void {
    if (!sugs.length) return this.setContent('<p class="empty">No tickers yet — ingest more events.</p>');
    const rows = sugs
      .map((s) => {
        const color = s.latest_verdict ? verdictColor(s.latest_verdict) : VIZ_COLORS.muted;
        const surge = (s.momentum ?? 1) >= 1.5 ? ` · ${Number(s.momentum).toFixed(1)}× surge` : "";
        return (
          `<button class="sug-row sug-click" data-sym="${escapeHtml(s.ticker)}" title="chart ${escapeHtml(s.ticker)} and its calls">` +
          `<span class="sug-dot" style="background:${color}"></span>` +
          `<b>${escapeHtml(s.ticker)}</b>` +
          `<span class="muted">${s.mentions} events · avg ${s.avg_score >= 0 ? "+" : ""}${s.avg_score}` +
          ` · ${escapeHtml(s.sector ?? "—")} · trust ${Math.round(s.trust * 100)}%${surge}</span>` +
          (s.latest_subject
            ? `<span class="muted sug-sub">${escapeHtml(s.latest_verdict ?? "")} · ${escapeHtml(s.latest_subject.slice(0, 90))}</span>`
            : "") +
          `</button>`
        );
      })
      .join("");
    this.setContent(`<div class="sug-list">${rows}</div>`);
  }
}

/** How much scored history backs a scenario, in words a reader can act on. */
export function evidence(scenario: Pick<Scenario, "data_tier" | "sample_size">): string {
  const n = scenario.sample_size ?? 0;
  if (scenario.data_tier === "empirical") return `backed by ${n} scored calls`;
  if (scenario.data_tier === "thin-data") return `thin record (${n} scored calls)`;
  return "analysis only, no scored record for this call";
}

export class CandlesPanel extends Panel {
  private symbol = "AAPL";
  private period = "1mo";
  // setContent paints on the next frame, so the shell is not in this.el yet when
  // the first refresh runs; keep the element itself.
  private shell: HTMLElement | null = null;

  constructor(
    private readonly events: () => EventOut[] = () => [],
    private readonly onSelect: (e: EventOut) => void = () => {},
  ) {
    super({ id: "candles", title: "Chart", w: 8, h: 8 });
    // any panel can point the chart at a symbol
    window.addEventListener("worldfin:select-symbol", (e) => {
      const sym = (e as CustomEvent<string>).detail?.toUpperCase();
      if (sym) {
        this.symbol = sym;
        void this.load();
      }
    });
  }

  async load(): Promise<void> {
    this.renderShell();
    await this.refresh();
  }

  /** Aim the chart without loading it; `load` draws it. */
  setSymbol(symbol: string): void {
    this.symbol = symbol.toUpperCase();
  }

  private renderShell(): void {
    const wrap = document.createElement("div");
    wrap.className = "candles";
    wrap.innerHTML =
      `<form class="candles-form">` +
      `<input class="candles-symbol" value="${escapeHtml(this.symbol)}" maxlength="16" />` +
      `<select class="candles-period">` +
      ["1d", "5d", "1mo", "3mo", "6mo", "1y"]
        .map((p) => `<option${p === this.period ? " selected" : ""}>${p}</option>`)
        .join("") +
      `</select><button type="submit">Load</button></form>` +
      `<div class="candles-body"><p class="muted">Loading…</p></div>` +
      `<div class="candles-calls"></div>`;
    wrap.addEventListener("click", (e) => {
      const id = Number((e.target as HTMLElement).closest<HTMLElement>("[data-event-id]")?.dataset.eventId);
      const event = this.events().find((ev) => ev.id === id);
      if (event) this.onSelect(event);
    });
    wrap.querySelector("form")!.addEventListener("submit", (e) => {
      e.preventDefault();
      const input = wrap.querySelector<HTMLInputElement>(".candles-symbol")!;
      this.symbol = input.value.toUpperCase().trim() || this.symbol;
      this.period = (wrap.querySelector<HTMLSelectElement>(".candles-period")!).value;
      void this.refresh();
    });
    this.shell = wrap;
    this.setContent(wrap);
  }

  private async refresh(): Promise<void> {
    const body = this.shell?.querySelector<HTMLElement>(".candles-body");
    const title = this.el.querySelector<HTMLElement>(".panel-head");
    if (title) title.textContent = `Chart — ${this.symbol} (${this.period})`;
    if (!body) return;
    this.renderCalls();
    body.innerHTML = '<p class="muted">Loading…</p>';
    try {
      const data = await api.candles(this.symbol, this.period);
      body.innerHTML = this.renderCandles(data.candles);
    } catch {
      body.innerHTML = '<p class="empty">No candle data for this symbol/period.</p>';
    }
  }

  /** The calls that named this symbol, so the chart reads against the news. */
  private renderCalls(): void {
    const box = this.shell?.querySelector<HTMLElement>(".candles-calls");
    if (!box) return;
    const calls = this.events().filter((e) => e.tickers.includes(this.symbol));
    box.innerHTML =
      `<h4 class="sub-head">Calls naming ${escapeHtml(this.symbol)} (${calls.length})</h4>` +
      (calls.length
        ? `<ul class="call-list">${calls
            .slice(0, 12)
            .map(
              (e) =>
                `<li data-event-id="${e.id}"><span class="dot" style="background:${verdictColor(e.verdict)}"></span>` +
                `<b>${escapeHtml(e.verdict)} ${e.signal_score >= 0 ? "+" : ""}${e.signal_score}</b> ` +
                `<span>${escapeHtml(e.subject)}</span> <span class="muted">${timeAgo(e.timestamp)}</span></li>`,
            )
            .join("")}</ul>`
        : '<p class="muted">No loaded event names this symbol.</p>');
  }

  private renderCandles(candles: Candle[]): string {
    if (candles.length < 2) return '<p class="empty">Not enough data.</p>';
    const w = 860;
    const h = 320;
    const volH = 56; // bottom band for volume
    const pad = 8;
    const highs = candles.map((c) => c.h);
    const lows = candles.map((c) => c.l);
    const max = Math.max(...highs);
    const min = Math.min(...lows);
    const span = max - min || 1;
    const priceH = h - volH - pad * 2;
    const step = (w - pad * 2) / candles.length;
    const bw = Math.max(2, step * 0.62);
    const y = (v: number): number => pad + (1 - (v - min) / span) * priceH;

    // SMA20 overlay
    const sma: Array<{ x: number; v: number }> = [];
    for (let i = 19; i < candles.length; i++) {
      const avg = candles.slice(i - 19, i + 1).reduce((s, c) => s + c.c, 0) / 20;
      sma.push({ x: pad + i * step + step / 2, v: avg });
    }
    const smaPath = sma.map((s, i) => `${i === 0 ? "M" : "L"}${s.x.toFixed(1)},${y(s.v).toFixed(1)}`).join(" ");

    const maxVol = Math.max(...candles.map((c) => c.v), 1);
    const volY = h - pad;

    const bars = candles
      .map((c, i) => {
        const x = pad + i * step + step / 2;
        const up = c.c >= c.o;
        const color = up ? "#16c784" : "#ea3943";
        const yH = y(c.h);
        const yL = y(c.l);
        const yO = y(c.o);
        const yC = y(c.c);
        const top = Math.min(yO, yC);
        const bodyH = Math.max(1.5, Math.abs(yC - yO));
        const vh = Math.max(1, (c.v / maxVol) * (volH - 6));
        return (
          `<line x1="${x.toFixed(1)}" y1="${yH.toFixed(1)}" x2="${x.toFixed(1)}" y2="${yL.toFixed(1)}" stroke="${color}" stroke-width="1"/>` +
          `<rect x="${(x - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${color}"/>` +
          `<rect x="${(x - bw / 2).toFixed(1)}" y="${(volY - vh).toFixed(1)}" width="${bw.toFixed(1)}" height="${vh.toFixed(1)}" fill="${color}" opacity="0.35"/>`
        );
      })
      .join("");

    const smaLine = sma.length > 1 ? `<path d="${smaPath}" fill="none" stroke="#f5a623" stroke-width="1.4"/>` : "";

    const last = candles[candles.length - 1];
    const first = candles[0];
    const chg = (((last.c - first.c) / first.c) * 100).toFixed(2);
    const cls = last.c >= first.c ? "up" : "down";
    return (
      `<div class="candles-head"><b>${escapeHtml(String(last.c))}</b>` +
      `<span class="${cls}"> ${Number(chg) >= 0 ? "+" : ""}${chg}% over period</span>` +
      `<span class="muted"> · SMA20 <span style="color:#f5a623">─</span> · volume ▄</span></div>` +
      `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="candles-svg">${bars}${smaLine}</svg>` +
      `<div class="muted candles-foot">${candles.length} candles</div>`
    );
  }
}

/** ".25-.5" and friends collapse to the midpoint the bucket stands for. */
function bucketMidpoint(bucket: string): number {
  const [lo, hi] = bucket.split("-").map(Number.parseFloat);
  if (!Number.isFinite(lo)) return 0.5;
  return Number.isFinite(hi) ? (lo + hi) / 2 : lo;
}

const TIER_NOTE: Record<string, string> = {
  empirical: "from past outcomes",
  "thin-data": "few past outcomes, mostly prior",
  "no-outcomes": "prior only, no outcomes yet",
};

export class PredictionPanel extends Panel {
  constructor() {
    super({ id: "prediction", title: "Calibration — is the stated confidence honest?", w: 6, h: 7 });
  }
  async load(): Promise<void> {
    this.el.addEventListener("click", (e) => {
      const sym = (e.target as HTMLElement).closest<HTMLElement>(".sug-click")?.dataset.sym;
      if (sym) window.dispatchEvent(new CustomEvent("worldfin:select-symbol", { detail: sym }));
    });
    try {
      const rel = await api.reliability();
      const events = (await api.events({ limit: 30 })).filter((e) => e.verdict !== "OBSERVE").slice(0, 5);
      const predictions = await Promise.allSettled(events.map((e) => api.predict(e.id)));

      const relTable = rel.reliability;
      const brier = rel.brier.brier == null ? "—" : rel.brier.brier.toFixed(3);
      const n = relTable.sample_size;

      const verds = barChart(
        Object.entries(relTable.by_verdict)
          .filter(([, s]) => s.hit_rate != null)
          .sort((a, b) => (b[1].hit_rate ?? 0) - (a[1].hit_rate ?? 0))
          .map(([v, s]) => ({
            label: v,
            value: Math.round((s.hit_rate ?? 0) * 100),
            color: verdictColor(v),
            note: `${Math.round((s.hit_rate ?? 0) * 100)}% · w ${s.weight}`,
          })),
        "hit rate by verdict",
      );

      const curve = calibration(
        Object.entries(relTable.by_confidence)
          .filter(([, s]) => s.hit_rate != null)
          .map(([bucket, s]) => ({
            predicted: bucketMidpoint(bucket),
            observed: s.hit_rate ?? 0,
            weight: s.weight,
            label: bucket,
          })),
        "observed hit rate against stated confidence",
      );

      const cards = predictions
        .filter((p) => p.status === "fulfilled")
        .map((p) => {
          const pr = (p as PromiseFulfilledResult<Prediction>).value;
          const pct = Math.round(pr.p_verdict_correct * 100);
          return (
            `<div class="pred-card">` +
            `<div class="pred-top"><b>${escapeHtml(pr.event.verdict)}${pr.event.ticker ? ` · ${escapeHtml(pr.event.ticker)}` : ""}</b>` +
            `<span class="pred-p">${pct}%</span></div>` +
            `<div class="pred-subj">${escapeHtml(pr.event.subject)}</div>` +
            `<div class="pred-bar"><i style="width:${pct}%;background:${pct >= 55 ? "#16c784" : pct <= 45 ? "#ea3943" : "#f5a623"}"></i></div>` +
            `<div class="muted pred-note">chance the call is right · ${TIER_NOTE[pr.data_tier] ?? pr.data_tier}</div>` +
            `</div>`
          );
        })
        .join("");

      this.setContent(
        `<div class="pred-summary">` +
          `<span>Global base rate: <b>${relTable.global_hit_rate == null ? "—" : Math.round(relTable.global_hit_rate * 100)}%</b></span>` +
          `<span class="muted"> · ${n} outcomes · Brier ${brier} · recency-decayed</span></div>` +
        `<div class="pred-grid">${cards || '<p class="empty">No directional signals yet.</p>'}</div>` +
        `<div class="pred-charts">` +
          `<div class="pred-table">${verds || '<p class="empty">No scored verdicts yet.</p>'}</div>` +
          (curve
            ? `<figure class="pred-cal">${curve}` +
              `<figcaption class="muted">Confidence vs outcome · dashed line is perfect ` +
              `calibration; above it is underconfident, below it overconfident.</figcaption></figure>`
            : "") +
        `</div>`,
      );
    } catch {
      this.setContent('<p class="empty">Prediction engine unavailable.</p>');
    }
  }
}

export class CalendarPanel extends Panel {
  constructor(private readonly onPick: (day: string) => void) {
    super({ id: "calendar", title: "Events per day — pick a day to load it", w: 8, h: 4 });
  }
  update(dates: DateCount[]): void {
    if (!dates.length) return this.setContent('<p class="empty">No dates.</p>');
    // Oldest-first so the volume histogram reads left to right like every other chart.
    const series = [...dates].reverse();
    const items = dates
      .map(
        (d) =>
          `<button class="day" data-day="${d.day}">${d.day} <span class="muted">(${d.count})</span></button>`,
      )
      .join("");
    const total = series.reduce((a, d) => a + d.count, 0);
    const peak = series.reduce((a, d) => (d.count > a.count ? d : a), series[0]);
    const wrap = document.createElement("div");
    wrap.className = "cal";
    wrap.innerHTML =
      columns(series.map((d) => d.count), "events per day") +
      `<div class="muted cal-meta">${total} events over ${series.length} days · ` +
      `peak ${peak.count} on ${escapeHtml(peak.day)}</div>` +
      items;
    wrap.addEventListener("click", (e) => {
      const t = e.target as HTMLElement;
      const day = t.closest<HTMLElement>(".day")?.dataset.day;
      if (day) this.onPick(day);
    });
    this.setContent(wrap);
  }
}

export class AccuracyPanel extends Panel {
  constructor() {
    super({ id: "accuracy", title: "Track record", w: 6, h: 7 });
  }
  async load(): Promise<void> {
    try {
      this.render(await api.accuracy());
    } catch {
      this.setContent('<p class="empty">Track record unavailable.</p>');
    }
  }
  private render(a: Accuracy): void {
    if (!a.scored) {
      this.setContent('<p class="empty">No scored calls yet — a call is scored once its window closes.</p>');
      return;
    }
    const horizons: Array<[string, HitRate | undefined, string]> = [
      ["Next day", a, "move toward the call ≥ 1%"],
      ["+2 days vs SPY", a.vs_spy?.d2, "beat SPY in the called direction"],
      ["+4 days vs SPY", a.vs_spy?.d4, "beat SPY in the called direction"],
    ];
    const cards = horizons
      .map(([label, h, rule]) => {
        if (!h?.scored) return `<div class="kpi"><span class="kpi-label">${label}</span><b>—</b></div>`;
        const [lo, hi] = wilson(h.hits, h.scored);
        return (
          `<div class="kpi" title="${escapeHtml(rule)}"><span class="kpi-label">${label}</span>` +
          `<b>${pct(h.hit_rate)}</b><span class="muted">${h.hits}/${h.scored} · 95% ${pct(lo)}–${pct(hi)}</span></div>`
        );
      })
      .join("");
    const verdicts = [...new Set(horizons.flatMap(([, h]) => Object.keys(h?.by_verdict ?? {})))];
    const cell = (h: HitRate | undefined, v: string): string => {
      const b = h?.by_verdict?.[v];
      return b ? `<td>${pct(b.hit_rate)} <span class="muted">${b.total}</span></td>` : "<td>—</td>";
    };
    const table =
      `<table class="grid-table"><thead><tr><th>Call</th>${horizons.map(([l]) => `<th>${l}</th>`).join("")}</tr></thead><tbody>` +
      verdicts
        .map(
          (v) =>
            `<tr><td><span class="dot" style="background:${verdictColor(v)}"></span>${escapeHtml(v)}</td>` +
            horizons.map(([, h]) => cell(h, v)).join("") +
            `</tr>`,
        )
        .join("") +
      `</tbody></table>`;
    const dd = a.equity_metrics?.max_drawdown;
    const wrap = document.createElement("div");
    wrap.className = "acc";
    wrap.innerHTML =
      `<div class="kpis">${cards}</div>` +
      table +
      `<h4 class="sub-head">Hits minus misses, in event order</h4>` +
      sparkline(a.equity_curve, "hits minus misses", signColor(a.equity_curve.at(-1) ?? 0)) +
      `<p class="muted note">${a.total - a.scored} of ${a.total} calls moved less than 1% and are not counted next day.` +
      (dd == null ? "" : ` Following every call with equal stakes: worst drawdown ${fmtPct(dd * 100)}.`) +
      `</p>`;
    this.setContent(wrap);
  }
}

export class OutcomesPanel extends Panel {
  constructor() {
    super({ id: "outcomes", title: "Scored calls", w: 12, h: 8 });
  }
  async load(): Promise<void> {
    try {
      this.render(await api.outcomes({ limit: 100 }));
    } catch {
      this.setContent('<p class="empty">Scored calls unavailable.</p>');
    }
  }
  private render(rows: Outcome[]): void {
    if (!rows.length) return this.setContent('<p class="empty">No call has been scored yet.</p>');
    const body = rows
      .map(
        (o) =>
          `<tr><td class="muted">${escapeHtml(o.timestamp.slice(0, 10))}</td>` +
          `<td><span class="dot" style="background:${verdictColor(o.verdict)}"></span>${escapeHtml(o.verdict)}</td>` +
          `<td class="subj-cell">${escapeHtml(o.subject)}</td>` +
          `<td>${escapeHtml(o.tickers.slice(0, 4).join(", "))}</td>` +
          `<td>${result(o.price_move_pct, o.correct)}</td>` +
          `<td>${result(o.ex2, o.correct2)}</td>` +
          `<td>${result(o.ex4, o.correct4)}</td></tr>`,
      )
      .join("");
    this.setContent(
      `<p class="muted note">Moves are signed toward the call: positive means the market went the way the call said.</p>` +
        `<table class="grid-table"><thead><tr><th>Date</th><th>Call</th><th>Event</th><th>Tickers</th>` +
        `<th>Next day</th><th>+2d vs SPY</th><th>+4d vs SPY</th></tr></thead><tbody>${body}</tbody></table>`,
    );
  }
}

function result(move: number | null, hit: boolean | null): string {
  if (move == null) return '<span class="muted">open</span>';
  const mark = hit == null ? "·" : hit ? "✓" : "✗";
  const cls = hit == null ? "muted" : hit ? "up" : "down";
  return `<span class="${cls}">${mark} ${fmtPct(move)}</span>`;
}

function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

/** 95% Wilson score interval for a hit rate. */
export function wilson(hits: number, n: number): [number, number] {
  if (!n) return [0, 0];
  const z = 1.96;
  const p = hits / n;
  const d = 1 + (z * z) / n;
  const mid = (p + (z * z) / (2 * n)) / d;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [Math.max(0, mid - half), Math.min(1, mid + half)];
}

// Per-source freshness. The worker has always recorded it and /api/health has always
// served it; without this panel a feed could go dark and nothing in the UI would say so.
const SOURCE_STATE: Record<string, { dot: string; label: string }> = {
  OK: { dot: "ok", label: "live" },
  STALE: { dot: "warn", label: "stale" },
  EMPTY: { dot: "warn", label: "empty" },
  WARN: { dot: "bad", label: "failing" },
  UNKNOWN: { dot: "idle", label: "unknown" },
};

export class SourceHealthPanel extends Panel {
  constructor() {
    super({ id: "sources", title: "Source health", w: 6, h: 8 });
  }

  private last: HealthResponse | null = null;

  async load(): Promise<void> {
    try {
      this.last = await api.health();
      this.render(this.last, false);
    } catch {
      this.render(this.last, true);
    }
  }

  /** A failed fetch keeps the last good answer on screen, marked as such. */
  private render(health: HealthResponse | null, failed: boolean): void {
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    status.className = "muted";
    if (failed) {
      status.textContent = health ? "Health unavailable, showing last known statuses. " : "Health unavailable. ";
      const retry = document.createElement("button");
      retry.type = "button";
      retry.textContent = "Retry";
      retry.addEventListener("click", () => void this.load());
      status.append(retry);
    }
    if (!health) {
      this.setContent(status);
      return;
    }
    const sources = [...health.sources].sort((a, b) => {
      const rank = (s: string) => (s === "WARN" ? 0 : s === "STALE" || s === "EMPTY" ? 1 : 2);
      return rank(a.status) - rank(b.status) || a.source.localeCompare(b.source);
    });
    const db = health.db ? "" : '<li class="src-row"><span class="src-dot bad"></span><b>database</b><span class="muted">unreachable</span></li>';
    if (!failed) {
      const attention = sources.filter((s) => s.status !== "OK").length;
      const newest = sources.map((s) => s.fetched_at).filter(Boolean).sort().at(-1) ?? null;
      status.textContent = attention
        ? `${plural(attention, "source")} need${attention === 1 ? "s" : ""} attention`
        : `All ${plural(sources.length, "source")} live · last fetch ${timeAgo(newest)}`;
    }
    if (!sources.length && !db) {
      this.setContent('<p class="empty">No sources have reported yet.</p>');
      return;
    }
    const rows = sources
      .map((s) => {
        const state = SOURCE_STATE[s.status] ?? SOURCE_STATE.UNKNOWN;
        return (
          `<li class="src-row" data-source="${escapeHtml(s.source)}" title="${escapeHtml(s.status)} — click to filter the feed">` +
          `<span class="src-dot ${state.dot}"></span>` +
          `<b>${escapeHtml(s.source)}</b>` +
          `<span class="muted">${escapeHtml(state.label)} · ${s.record_count} · ${timeAgo(s.fetched_at)}</span>` +
          `</li>`
        );
      })
      .join("");
    const list = document.createElement("ul");
    list.className = "src-list";
    list.innerHTML = `${db}${rows}`;
    list.addEventListener("click", (e) => {
      const source = (e.target as HTMLElement).closest<HTMLElement>("[data-source]")?.dataset.source;
      if (source) {
        window.dispatchEvent(new CustomEvent("worldfin:select-source", { detail: source }));
      }
    });
    const wrap = document.createElement("div");
    wrap.append(status, list);
    this.setContent(wrap);
  }
}


const STANCE_COLOR: Record<string, string> = {
  "risk-on": VIZ_COLORS.up,
  "risk-off": VIZ_COLORS.down,
  mixed: "#f5a623",
};

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** Legs are already ranked and signed by the engine — colour is the only translation. */
function legBars(legs: ScenarioLeg[], label: string): string {
  return barChart(
    legs.map((leg) => ({
      label: leg.name,
      value: Math.round(leg.strength * 100),
      color: leg.direction === "up" ? VIZ_COLORS.up : VIZ_COLORS.down,
      note: `${leg.direction === "up" ? "▲" : "▼"} ${leg.tilt >= 0 ? "+" : ""}${leg.tilt.toFixed(2)}`,
    })),
    label,
  );
}

export class ScenarioPanel extends Panel {

  constructor() {
    super({ id: "scenarios", title: "Scenarios — what to do about it", w: 12, h: 6 });
    this.el.addEventListener("click", (e) => {
      const sym = (e.target as HTMLElement).closest<HTMLElement>(".sc-tk")?.dataset.sym;
      if (sym) window.dispatchEvent(new CustomEvent("worldfin:select-symbol", { detail: sym }));
    });
  }

  async load(): Promise<void> {
    try {
      this.render(await api.scenarios());
    } catch {
      this.setContent('<p class="empty">Scenario engine unavailable.</p>');
    }
  }

  private render(scenarios: Scenario[]): void {
    if (!scenarios.length) {
      this.setContent(
        '<p class="empty">No scenario has formed yet — events cluster into one once ' +
          "two or more corroborate.</p>",
      );
      return;
    }
    this.setContent(
      `<div class="sc-grid">${scenarios.map((s) => this.card(s)).join("")}</div>`,
    );
  }

  private card(scenario: Scenario): string {
    const color = STANCE_COLOR[scenario.stance] ?? VIZ_COLORS.muted;
    const pct = Math.round(scenario.probability * 100);
    const chips = scenario.exposure
      .map(
        (leg) =>
          `<button class="sc-tk" data-sym="${escapeHtml(leg.name)}" title="net tilt ${leg.tilt.toFixed(2)}">` +
          `${escapeHtml(leg.name)} ${leg.direction === "up" ? "▲" : "▼"}</button>`,
      )
      .join("");
    const chain = scenario.chain
      .map((fx) => `<li>${escapeHtml(fx)}</li>`)
      .join("");
    // Divergence means the sources disagreed — the one caveat worth the space.
    const caveat =
      scenario.divergent_members > 0
        ? ` · <span class="sc-warn">${scenario.divergent_members} divergent</span>`
        : "";

    return (
      `<article class="sc-card" data-id="${escapeHtml(scenario.id)}">` +
      `<header class="sc-head">` +
      `<span class="sc-stance" style="background:${color}">${escapeHtml(scenario.stance)}</span>` +
      `<h4 class="sc-title">${escapeHtml(scenario.title)}</h4>` +
      `<span class="sc-prob" style="color:${color}" title="probability the ${escapeHtml(scenario.stance)} call plays out · ${escapeHtml(scenario.data_tier)}">${pct}%</span></header>` +
      `<div class="sc-bar"><i style="width:${pct}%;background:${color}"></i></div>` +
      `<p class="sc-advice">${escapeHtml(scenario.advice)}</p>` +
      (scenario.sectors.length ? legBars(scenario.sectors, "sector tilt") : "") +
      (chips ? `<div class="sc-chips">${chips}</div>` : "") +
      (chain ? `<ul class="sc-chain">${chain}</ul>` : "") +
      `<footer class="muted sc-meta">${plural(scenario.reports ?? scenario.size, "report")} · ` +
      `${escapeHtml(scenario.sources.slice(0, 3).map(sourceLabel).join(", ") || "no sources")} · ` +
      `${escapeHtml(evidence(scenario))}${caveat}</footer></article>`
    );
  }
}
