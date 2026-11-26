// Event page (plan m4.2.1): the row a call came from, read as evidence rather than
// as an opinion. Every block says where its data came from, and a field the row does
// not carry says "not recorded" instead of inventing one.

import { api, verdictColor, type EventOut } from "../api";
import { sourceLabel, signed } from "../util";
import { citeLink } from "../components/citation";
import { DASHBOARD } from "../app/routes";

export interface ScoreTrace {
  input: number;
  final: number;
  steps: string[];
}

export interface EventPageData extends EventOut {
  score_trace?: ScoreTrace;
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

/** The sentence in the stored excerpt that names `ticker`, or "" when it does not. */
export function backingSentence(text: string, ticker: string): string {
  if (!text) return "";
  const safe = ticker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(^|[^A-Za-z0-9])${safe}($|[^A-Za-z0-9])`);
  for (const sentence of text.split(/(?<=[.!?])\s+/)) {
    if (re.test(sentence)) return sentence.trim();
  }
  return "";
}

export function sectorChain(ev: EventPageData): Array<{ who: string; value: string }> | null {
  const raw = (ev.key_metrics ?? {})["sector_chain"] as
    | { laya?: string; model?: string; keyword?: string; chosen?: string }
    | undefined;
  if (!raw || typeof raw !== "object") return null;
  return [
    { who: "Laya", value: raw.laya || "no label" },
    { who: "Model", value: raw.model || "no label" },
    { who: "Keyword", value: raw.keyword || "no label" },
    { who: "Chosen", value: raw.chosen || ev.sector_impact || ev.sector || "other" },
  ];
}

function section(title: string, ...children: Node[]): HTMLElement {
  const box = el("section", "ev-block");
  box.append(el("h2", "ev-block-title", title), ...children);
  return box;
}

/** A paragraph whose only content is a citation anchor. */
function citeP(cls: string, html: string): HTMLElement {
  const p = el("p", cls);
  p.innerHTML = html;
  return p;
}

function sourcesBlock(ev: EventPageData): HTMLElement {
  const list = el("ul", "ev-sources");
  const seen = ev.source_seen ?? {};
  for (const tag of ev.sources ?? []) {
    const row = el("li");
    row.append(el("b", "", sourceLabel(tag)));
    const when = seen[tag];
    row.append(
      el("time", "ev-time", when ? new Date(when).toUTCString() : "arrival time not recorded"),
    );
    list.append(row);
  }
  if (!list.childElementCount) list.append(el("li", "empty", "No source was recorded."));
  if (!Object.keys(seen).length) {
    list.append(
      el(
        "li",
        "ev-note",
        "This row predates source timestamps; the story time is the only clock it has.",
      ),
    );
  }
  return section("Sources", list);
}

function excerptBlock(ev: EventPageData): HTMLElement {
  const text = (ev.excerpt ?? "").trim();
  if (!text) {
    return section(
      "Excerpt",
      el(
        "p",
        "empty",
        "No article excerpt was stored for this call. The reasoning below is all this row carries.",
      ),
      el("p", "ev-reasoning", ev.reasoning || "No reasoning stored either."),
    );
  }
  const quote = el("blockquote", "ev-excerpt", text);
  const urls = el("div", "ev-links");
  for (const url of ev.articles ?? []) {
    const a = el("a", "ev-link", "source article");
    a.href = url;
    a.rel = "noopener noreferrer";
    a.target = "_blank";
    urls.append(a);
  }
  return section("Excerpt", quote, urls);
}

function chainBlock(ev: EventPageData): HTMLElement {
  const chain = sectorChain(ev);
  if (!chain) {
    return section(
      "Sector chain",
      el(
        "p",
        "empty",
        `Chain not recorded for this row. Stored sector: ${ev.sector_impact || ev.sector || "other"}.`,
      ),
    );
  }
  const table = el("table", "ev-chain");
  for (const step of chain) {
    const tr = el("tr", step.who === "Chosen" ? "chosen" : "");
    tr.append(el("th", "", step.who), el("td", "", step.value));
    table.append(tr);
  }
  return section("Sector chain", table);
}

export interface Corroboration {
  source: string;
  type: string;
  at: string;
  deltaMs: number;
}

function sourceType(tag: string): string {
  const m = /:([a-z_]+)$/.exec(tag);
  return m ? m[1] : "unknown type";
}

function delta(ms: number): string {
  const mins = Math.round(ms / 60_000);
  if (mins < 60) return `+${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `+${h}h ${m}m` : `+${h}h`;
}

/** Sources in the order they carried the story, relative to the first one we saw. */
export function corroboration(ev: EventPageData): Corroboration[] {
  const seen = ev.source_seen ?? {};
  const rows = Object.entries(seen)
    .map(([source, at]) => ({ source, type: sourceType(source), at, ms: Date.parse(at) }))
    .filter((r) => Number.isFinite(r.ms))
    .sort((a, b) => a.ms - b.ms);
  if (!rows.length) return [];
  const first = rows[0].ms;
  return rows.map((r) => ({
    source: r.source,
    type: r.type,
    at: new Date(r.ms).toUTCString(),
    deltaMs: r.ms - first,
  }));
}

function corroborationBlock(ev: EventPageData): HTMLElement {
  const rows = corroboration(ev);
  if (!rows.length) {
    return section(
      "Corroboration",
      el(
        "p",
        "empty",
        "No source timestamps were recorded for this row, so independent confirmation cannot be shown.",
      ),
    );
  }
  const types = new Set(rows.map((r) => r.type));
  const list = el("ol", "ev-timeline");
  rows.forEach((row, i) => {
    const li = el("li");
    li.append(el("b", "", sourceLabel(row.source)));
    li.append(el("span", "ev-type", row.type));
    li.append(
      el(
        "time",
        "ev-time",
        i === 0 ? `${row.at} (first report)` : `${row.at} (${delta(row.deltaMs)} after the first)`,
      ),
    );
    list.append(li);
  });
  const verdict =
    types.size >= 2
      ? `${types.size} independent source types confirmed this story.`
      : "One source type only: this is a single-source story, not corroborated.";
  return section("Corroboration", list, el("p", "ev-note", verdict));
}

function whyBlock(ev: EventPageData): HTMLElement {
  const box = section("Why this call");
  const labels = el("div", "ev-labels");
  for (const [name, value] of [
    ["magnitude", ev.magnitude],
    ["actionability", ev.actionability],
    ["novelty", ev.novelty],
  ]) {
    labels.append(el("span", "ev-label", `${name}: ${value || "not recorded"}`));
  }
  box.append(labels);

  const who = el("p", "ev-who");
  if (ev.analysis_source === "heuristic") {
    who.textContent =
      "No model judged this row: the keyword fallback produced the verdict, so there is no model-vs-heuristic agreement to show.";
  } else {
    const model = ev.model_name ? `Model: ${ev.model_name}. ` : "Model name not recorded. ";
    who.textContent = ev.divergence_flag
      ? `${model}The keyword heuristic read the opposite direction, so the score was capped at +/-2.`
      : `${model}The keyword heuristic did not disagree on direction.`;
  }
  const what =
    ev.analysis_source === "heuristic" ? "why this call, keyword fallback" : "why this call";
  box.append(who, citeP("ev-cite", citeLink(ev, what)));

  const trace = ev.score_trace;
  if (trace) {
    const steps = el("ol", "ev-steps");
    for (const step of trace.steps) steps.append(el("li", "", step));
    box.append(steps);
    if (trace.final !== ev.signal_score) {
      box.append(
        el(
          "p",
          "ev-note",
          `Stored score ${signed(ev.signal_score)}; the rules alone give ${signed(trace.final)}. A disagreement cap or the tape moved the stored number.`,
        ),
      );
    }
  } else {
    box.append(el("p", "ev-note", "No score trace was returned for this row."));
  }
  return box;
}

function tickersBlock(ev: EventPageData): HTMLElement {
  const list = el("ul", "ev-tickers");
  const roles = new Map(
    (ev.affected_entities ?? []).filter((e) => e.ticker).map((e) => [e.ticker as string, e]),
  );
  for (const ticker of ev.tickers ?? []) {
    const li = el("li");
    const head = el("div", "ev-ticker-head");
    head.append(el("b", "", ticker));
    const role = roles.get(ticker);
    if (role?.role) head.append(el("span", "ev-role", role.role));
    li.append(head);
    const sentence = backingSentence(ev.excerpt ?? "", ticker);
    li.append(
      el(
        "p",
        sentence ? "ev-backing" : "ev-note",
        sentence ||
          "The stored excerpt does not name this symbol; it came from the entity index or the model.",
      ),
      citeP("ev-cite", citeLink(ev, ticker)),
    );
    list.append(li);
  }
  if (!list.childElementCount) list.append(el("li", "empty", "No ticker survived grounding."));
  return section("Tickers", list);
}

export function renderEventPage(ev: EventPageData): HTMLElement {
  const page = el("article", "event-page");
  const back = el("a", "ev-back", "Back to the dashboard");
  back.href = DASHBOARD;

  const head = el("header", "ev-head");
  const verdict = el("span", "ev-verdict", ev.verdict);
  verdict.style.color = verdictColor(ev.verdict);
  head.append(
    verdict,
    el("span", "ev-score", `${signed(ev.signal_score)} / 5`),
    el("h1", "ev-subject", ev.subject),
  );

  const meta = el("p", "ev-meta");
  meta.textContent = [
    ev.event_type,
    ev.sector_impact || ev.sector || "sector not recorded",
    ev.analysis_source ? `written by ${ev.analysis_source}` : "source not recorded",
    ev.model_name || "",
    `confidence ${Math.round((ev.confidence ?? 0) * 100)}%`,
    ev.timestamp ? new Date(ev.timestamp).toUTCString() : "",
  ]
    .filter(Boolean)
    .join(" ? ");

  const grid = el("div", "ev-grid");
  grid.append(
    sourcesBlock(ev),
    excerptBlock(ev),
    chainBlock(ev),
    tickersBlock(ev),
    whyBlock(ev),
    corroborationBlock(ev),
  );
  page.append(back, head, meta, grid);
  return page;
}

/** The routed view: owns the fetch and the error state, renders with renderEventPage. */
export class EventPageView {
  readonly el: HTMLElement;

  constructor() {
    this.el = el("div", "ev-host");
    this.el.hidden = true;
  }

  async load(id: number): Promise<void> {
    this.el.hidden = false;
    this.el.replaceChildren(el("p", "empty", "Loading event..."));
    try {
      const ev = (await api.event(id)) as EventPageData;
      this.el.replaceChildren(renderEventPage(ev));
    } catch {
      const box = el("div", "event-page");
      const back = el("a", "ev-back", "Back to the dashboard");
      back.href = DASHBOARD;
      box.append(
        back,
        el("h1", "ev-subject", `Event ${id} is not available`),
        el("p", "empty", "The API has no row with this id, or it could not be reached."),
      );
      this.el.replaceChildren(box);
    }
  }

  hide(): void {
    this.el.hidden = true;
  }
}
