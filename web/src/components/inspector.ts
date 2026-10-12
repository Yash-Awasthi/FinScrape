// Inspector: the selected signal, in a persistent right rail.
//
// Replaces the modal. A terminal keeps the detail beside the feed rather than over
// it, so j/k can walk rows and read each one without a dialog opening and closing.

import { type AIAnalysis, api, type Council, type EventOut, type Prediction, verdictColor } from "../api";
import { escapeHtml, fmtPct, sourceLabel, timeAgo } from "../util";

// A backup analysis job takes 1-2 minutes; stop asking after 4.
const PENDING_POLL_MS = 15_000;
const PENDING_POLLS = 16;

const PLACEHOLDER =
  '<p class="empty">Select a signal — click a row, or press j / k to walk the feed.</p>';

export class Inspector {
  readonly el: HTMLElement;
  private readonly body: HTMLElement;
  private current: number | null = null;

  constructor(private readonly onClose: () => void) {
    this.el = document.createElement("aside");
    this.el.className = "inspector";

    const head = document.createElement("header");
    head.className = "inspector-head";
    const title = document.createElement("span");
    title.textContent = "Inspector";
    const close = document.createElement("button");
    close.className = "inspector-close";
    close.textContent = "✕";
    close.title = "clear selection (Esc)";
    close.addEventListener("click", () => {
      this.reset();
      this.onClose();
    });
    head.append(title, close);

    this.body = document.createElement("div");
    this.body.className = "inspector-body";
    this.body.innerHTML = PLACEHOLDER;

    this.el.append(head, this.body);
  }

  get selectedId(): number | null {
    return this.current;
  }

  /** Back to the placeholder. Does not announce — the store owns the selection, and
   *  calling back into it from a store subscriber would loop. */
  reset(): void {
    this.current = null;
    this.body.innerHTML = PLACEHOLDER;
  }

  show(ev: EventOut): void {
    if (this.current === ev.id) return; // re-selecting the same row must not refetch
    this.current = ev.id;
    this.body.replaceChildren(
      this.header(ev),
      this.reasoning(ev),
      ...this.entities(ev),
      ...this.chain(ev),
      ...this.coverage(ev),
      ...this.prediction(ev),
      ...this.outcome(ev),
      ...this.analysis(ev),
      ...this.council(ev),
    );
  }

  private header(ev: EventOut): HTMLElement {
    const wrap = document.createElement("div");
    const badge = document.createElement("span");
    badge.className = "verdict-badge";
    badge.style.background = verdictColor(ev.verdict);
    badge.textContent = `${ev.verdict} ${ev.signal_score >= 0 ? "+" : ""}${ev.signal_score}`;

    const h = document.createElement("h2");
    const link = ev.articles?.[0];
    h.innerHTML = link
      ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(ev.subject)}</a>`
      : escapeHtml(ev.subject);

    const meta = document.createElement("div");
    meta.className = "insp-meta";
    meta.textContent =
      `${ev.event_type} · ${ev.sector_impact || "no sector"} · confidence ${Math.round(ev.confidence * 100)}% · ` +
      `${ev.magnitude} magnitude · ${timeAgo(ev.timestamp)} ago · ${ev.tickers.join(", ") || "no tickers"}`;

    wrap.append(badge, h, meta);
    return wrap;
  }

  private reasoning(ev: EventOut): HTMLElement {
    const p = document.createElement("p");
    p.className = "insp-reasoning";
    p.textContent = ev.reasoning || "";
    return p;
  }

  private entities(ev: EventOut): HTMLElement[] {
    const list = (ev.affected_entities ?? []).filter((e) => e?.name);
    if (!list.length) return [];
    const ul = document.createElement("ul");
    ul.className = "insp-entities";
    for (const ent of list) {
      const li = document.createElement("li");
      li.textContent = `${ent.name}${ent.ticker ? ` (${ent.ticker})` : ""} — ${ent.role ?? "?"} / ${ent.impact ?? "?"}`;
      ul.append(li);
    }
    return [ul];
  }

  private chain(ev: EventOut): HTMLElement[] {
    const effects = (ev.second_order_effects ?? []).filter(Boolean);
    if (!effects.length) return [];
    const head = document.createElement("h3");
    head.className = "insp-section";
    head.textContent = `Second-order chain (${effects.length})`;
    const ul = document.createElement("ul");
    ul.className = "insp-chain";
    for (const fx of effects) {
      const li = document.createElement("li");
      li.textContent = `⚡ ${fx}`;
      ul.append(li);
    }
    return [head, ul];
  }

  /** Every article merged into this event: corroboration is the evidence. */
  private coverage(ev: EventOut): HTMLElement[] {
    const head = document.createElement("h3");
    head.className = "insp-section";
    head.textContent = `Coverage (${ev.articles.length} article${ev.articles.length === 1 ? "" : "s"}, ${ev.sources.length} source${ev.sources.length === 1 ? "" : "s"})`;
    const ul = document.createElement("ul");
    ul.className = "insp-links";
    ul.innerHTML = ev.articles
      .slice(0, 8)
      // Articles and sources are deduped separately, so their positions do not pair up.
      .map((url) => `<li><a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(host(url))}</a></li>`)
      .join("");
    const from = document.createElement("p");
    from.className = "muted";
    from.textContent = `Sources: ${ev.sources.map(sourceLabel).join(", ") || "—"}`;
    return [head, ul, from];
  }

  /** How the call did once its window closed, or why it has no score. */
  private outcome(ev: EventOut): HTMLElement[] {
    const head = document.createElement("h3");
    head.className = "insp-section";
    head.textContent = "Outcome";
    const box = document.createElement("div");
    box.className = "insp-outcome";
    if (ev.verdict !== "INVEST" && ev.verdict !== "PULL_OUT") {
      box.textContent = `${ev.verdict} is not a directional call, so it is not scored.`;
      return [head, box];
    }
    box.textContent = "…";
    void api
      .outcomes({ event_id: ev.id })
      .then(([o]) => {
        if (this.current !== ev.id) return;
        if (!o) {
          box.textContent = "Not scored yet: the next trading day has not closed, or no price data.";
          return;
        }
        const line = (label: string, move: number | null, hit: boolean | null): string =>
          move == null
            ? `<li>${label}: <span class="muted">window open</span></li>`
            : `<li>${label}: <span class="${hit == null ? "muted" : hit ? "up" : "down"}">${hit == null ? "under 1%, not counted" : hit ? "right" : "wrong"} ${fmtPct(move)}</span></li>`;
        box.innerHTML =
          `<ul>${line("Next day", o.price_move_pct, o.correct)}${line("+2 days vs SPY", o.ex2, o.correct2)}` +
          `${line("+4 days vs SPY", o.ex4, o.correct4)}</ul>`;
      })
      .catch(() => {
        if (this.current === ev.id) box.textContent = "Outcome unavailable.";
      });
    return [head, box];
  }

  /** Analyst personas debate the event; a judge reads the transcript. Opt-in server-side. */
  private council(ev: EventOut): HTMLElement[] {
    const btn = document.createElement("button");
    btn.className = "ai-btn secondary";
    btn.textContent = "Ask the analyst council";
    const out = document.createElement("div");
    out.className = "ai-out";
    btn.addEventListener("click", () => {
      btn.disabled = true;
      out.textContent = "The council is debating (up to a minute)…";
      api
        .council(ev.id)
        .then((c: Council) => {
          if (this.current !== ev.id) return;
          out.innerHTML =
            `<b>${escapeHtml(c.consensus_verdict)}</b> · score ${c.consensus_score >= 0 ? "+" : ""}${c.consensus_score} · ` +
            `${Math.round(c.agreement_level * 100)}% agreement` +
            (c.dissenting_agents.length ? ` · dissent: ${escapeHtml(c.dissenting_agents.join(", "))}` : "") +
            list("Risks", c.key_risks) +
            list("Opportunities", c.key_opportunities);
        })
        .catch((err: Error) => {
          if (this.current !== ev.id) return;
          out.textContent = err.message.includes("404")
            ? "The council is switched off on this server (WORLDFIN_ENABLE_COUNCIL)."
            : "Council unavailable.";
        })
        .finally(() => {
          btn.disabled = false;
        });
    });
    return [btn, out];
  }

  /** Calibrated probability the verdict's direction realizes, with its sample size. */
  private prediction(ev: EventOut): HTMLElement[] {
    const head = document.createElement("h3");
    head.className = "insp-section";
    head.textContent = "Calibrated probability";
    const box = document.createElement("div");
    box.className = "p-box";
    box.textContent = "…";

    void api
      .predict(ev.id)
      .then((p: Prediction) => {
        if (this.current !== ev.id) return; // selection moved on while we waited
        const pct = Math.round(p.p_verdict_correct * 100);
        box.innerHTML =
          `<div class="p-bar"><span style="width:${pct}%"></span></div>` +
          `<div class="p-meta"><b>${pct}%</b> ${escapeHtml(p.expected_direction)} · ` +
          `${escapeHtml(p.data_tier)} · n=${p.reliability_tables.sample_size}</div>`;
      })
      .catch(() => {
        if (this.current === ev.id) box.textContent = "No calibration yet.";
      });
    return [head, box];
  }

  private analysis(ev: EventOut): HTMLElement[] {
    const out = document.createElement("div");
    out.className = "ai-out";
    const btn = document.createElement("button");
    btn.className = "ai-btn";
    btn.textContent = "Run AI analysis";
    out.textContent = "AI analysis runs only when asked; free models have daily limits.";

    const show = (a: AIAnalysis): void => {
      const impacts = a.ticker_impacts
        .map((t) => `${t.ticker}: ${t.direction} ${t.estimated_pct} — ${t.reason}`)
        .join("\n");
      out.textContent =
        [a.summary, impacts, a.verdict_reason].filter(Boolean).join("\n\n") ||
        "No analysis returned.";
    };

    const run = async (): Promise<void> => {
      btn.disabled = true;
      out.textContent = "AI is analyzing…";
      try {
        let a = await api.analyze(ev.id);
        // Free models busy: a backup job is analysing on another host, so poll the cache.
        for (let i = 0; a.pending && i < PENDING_POLLS; i++) {
          if (this.current !== ev.id) return;
          out.textContent = "Free models are busy; the backup model is analysing (about 1–2 min)…";
          await new Promise((r) => setTimeout(r, PENDING_POLL_MS));
          a = await api.analyze(ev.id);
        }
        if (this.current !== ev.id) return;
        if (a.heuristic) {
          out.textContent = "AI models are unavailable right now. Try again in a few minutes.";
          return;
        }
        show(a);
      } catch {
        if (this.current !== ev.id) return;
        out.textContent = "AI analysis unavailable.";
      } finally {
        btn.disabled = false;
      }
    };
    btn.addEventListener("click", () => void run());
    return [btn, out];
  }
}

function list(title: string, items: string[]): string {
  if (!items.length) return "";
  return `<h4 class="insp-section">${title}</h4><ul>${items.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`;
}

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
