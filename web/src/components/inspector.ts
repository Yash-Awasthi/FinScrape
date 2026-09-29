// Inspector: the selected signal, in a persistent right rail.
//
// Replaces the modal. A terminal keeps the detail beside the feed rather than over
// it, so j/k can walk rows and read each one without a dialog opening and closing.

import { api, type EventOut, type Prediction, verdictColor } from "../api";
import { escapeHtml, sourceLabel } from "../util";

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
      ...this.prediction(ev),
      ...this.analysis(ev),
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
    meta.textContent = `${ev.event_type} · ${Math.round(ev.confidence * 100)}% · ${ev.tickers.join(", ") || "no tickers"} · ${ev.sources.map(sourceLabel).join(", ")}`;

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
    btn.textContent = "↻ Re-run AI analysis";

    const run = async (): Promise<void> => {
      btn.disabled = true;
      out.textContent = "AI is analyzing… (local model, a few seconds)";
      try {
        const a = await api.analyze(ev.id);
        if (this.current !== ev.id) return;
        const impacts = a.ticker_impacts
          .map((t) => `${t.ticker}: ${t.direction} ${t.estimated_pct} — ${t.reason}`)
          .join("\n");
        out.textContent =
          [a.summary, impacts, a.verdict_reason].filter(Boolean).join("\n\n") ||
          "No analysis returned.";
      } catch (err) {
        if (this.current !== ev.id) return;
        out.textContent =
          err instanceof Error && err.message.includes("503")
            ? "AI backend unavailable — start Ollama, then: main.py devtools on"
            : "AI analysis unavailable.";
      } finally {
        btn.disabled = false;
      }
    };
    btn.addEventListener("click", () => void run());

    // Reasoning must never sit blank: events stored without the LLM analyze on open.
    if (!ev.reasoning) void run();
    return [btn, out];
  }
}
