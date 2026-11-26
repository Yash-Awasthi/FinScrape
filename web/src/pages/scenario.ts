// Scenario page (plan m4.2.2): the cluster's members, its probability with the
// interval it actually has, the tilt it implies, and the window it was built from.

import { api, type Scenario } from "../api";
import { DASHBOARD } from "../app/routes";

export interface ScenarioMember {
  id: number;
  subject: string;
  verdict: string;
  signal_score: number;
  confidence: number;
  sector_impact: string;
  timestamp: string | null;
  sources: string[];
}

export interface HistoryPoint {
  probability: number;
  n_members: number;
  at: string | null;
}

export interface ScenarioWindow {
  events_considered: number;
  event_cap: number;
  lookback_days: number;
}

export interface WhatIf {
  excluded_id: number;
  probability: number;
  n_members: number;
  ci95: [number, number] | null;
  label: string;
}

export interface ScenarioDetail {
  scenario: Scenario;
  members: ScenarioMember[];
  /** One point per stored recompute, oldest first; empty when none was stored. */
  history?: HistoryPoint[];
  window: ScenarioWindow;
  /** Present when the caller dropped a member: a recompute, not the stored call. */
  what_if?: WhatIf | null;
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

export function probabilityLine(s: Scenario): string {
  const pct = Math.round(s.probability * 100);
  const n = s.n_members ?? s.size;
  const ci = s.ci95;
  if (!ci) {
    return `${pct}% ? ${n} member call${n === 1 ? "" : "s"} ? one member carries no spread, so no interval`;
  }
  return `${pct}% ? ${n} member calls ? 95% interval ${Math.round(ci[0] * 100)}-${Math.round(ci[1] * 100)}%`;
}

const W = 260;
const H = 56;

/**
 * Probability over time on a fixed 50-100% axis, so a flat line reads as flat
 * rather than as noise stretched to fill the box.
 */
export function probabilityChart(history: HistoryPoint[]): string | null {
  const points = history.filter((h) => Number.isFinite(h.probability));
  if (points.length < 2) return null;
  const y = (p: number) => (H - ((Math.min(1, Math.max(0.5, p)) - 0.5) / 0.5) * H).toFixed(1);
  const line = points
    .map((p, i) => `${((i / (points.length - 1)) * W).toFixed(1)},${y(p.probability)}`)
    .join(" ");
  const last = points[points.length - 1];
  return (
    `<svg class="sc-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" ` +
    `aria-label="scenario probability, ${points.length} recomputes, ${Math.round(points[0].probability * 100)} to ${Math.round(last.probability * 100)} percent">` +
    `<line class="sc-base" x1="0" y1="${H - 0.5}" x2="${W}" y2="${H - 0.5}"/>` +
    `<polyline points="${line}" fill="none" class="sc-line"/>` +
    `<circle cx="${W}" cy="${y(last.probability)}" r="2.5" class="sc-dot"/></svg>`
  );
}

/**
 * The same scenario with one member dropped (or the stored one when `exclude`
 * is null). Plain fetch: the shared api module keeps its own shape, and a
 * hypothetical must never be cached as the real call.
 */
export async function loadScenarioDetail(
  id: string,
  exclude: number | null,
): Promise<ScenarioDetail> {
  const query = exclude === null ? "" : `?exclude=${exclude}`;
  const res = await fetch(`/api/scenarios/${encodeURIComponent(id)}${query}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`scenario ${id} failed (${res.status})`);
  return (await res.json()) as ScenarioDetail;
}

function whatIfStrip(whatIf: WhatIf, restore: (button: HTMLButtonElement) => void): HTMLElement {
  const box = el("section", "ev-block");
  box.append(el("h2", "ev-block-title", `Hypothetical: event #${whatIf.excluded_id} removed`));
  const pct = Math.round(whatIf.probability * 100);
  box.append(
    el(
      "p",
      "sc-prob-line",
      `Probability ${pct}% (n=${whatIf.n_members}) - not the stored scenario.`,
    ),
  );
  const button = el("button", "ai-btn secondary", "Restore the real scenario");
  button.type = "button";
  button.onclick = () => restore(button);
  box.append(button);
  return box;
}

function historyBlock(detail: ScenarioDetail): HTMLElement {
  const history = detail.history ?? [];
  const box = el("section", "ev-block");
  box.append(el("h2", "ev-block-title", "Probability history"));
  if (!history.length) {
    box.append(
      el(
        "p",
        "empty",
        "No recompute has been stored for this scenario yet, so it has one number and no trend.",
      ),
    );
    return box;
  }
  const chart = probabilityChart(history);
  if (chart) {
    const host = el("div", "sc-chart");
    host.innerHTML = chart;
    box.append(host);
  }
  const first = history[0];
  const last = history[history.length - 1];
  box.append(
    el(
      "p",
      "ev-note",
      history.length < 2
        ? `One stored recompute (${Math.round(first.probability * 100)}%); a second one is needed before this is a trend.`
        : `${history.length} stored recomputes from ${first.at ?? "time not recorded"} to ${last.at ?? "time not recorded"}, on a 50-100% axis. Each point is this scenario rebuilt from the events in its window, not a market price.`,
    ),
  );
  return box;
}

function legs(rows: Scenario["sectors"], label: string): HTMLElement {
  const box = el("section", "ev-block");
  box.append(el("h2", "ev-block-title", label));
  const list = el("ul", "ev-sources");
  for (const leg of rows) {
    const li = el("li");
    li.append(
      el("b", "", leg.name),
      el(
        "span",
        "ev-time",
        `${leg.direction === "up" ? "up" : "down"} ? tilt ${leg.tilt.toFixed(2)}`,
      ),
    );
    list.append(li);
  }
  if (!list.childElementCount) list.append(el("li", "empty", "No tilt recorded."));
  box.append(list);
  return box;
}

export function renderScenarioPage(detail: ScenarioDetail): HTMLElement {
  const { scenario, members, window, what_if: whatIf } = detail;
  const page = el("article", "event-page scenario-page");
  // A what-if is a different page, not an in-place tweak: swap the whole article
  // so the strip and every number come from the response that produced them.
  const swap = (next: ScenarioDetail) => page.replaceWith(renderScenarioPage(next));
  const apply = async (exclude: number | null) =>
    swap(await loadScenarioDetail(scenario.id, exclude));
  const restore = (button: HTMLButtonElement) => {
    button.disabled = true;
    apply(null).catch(() => {
      button.disabled = false;
      button.textContent = "Restore failed - try again";
    });
  };
  const back = el("a", "ev-back", "Back to the dashboard");
  back.href = DASHBOARD;

  const head = el("header", "ev-head");
  head.append(el("span", "ev-verdict", scenario.stance), el("h1", "ev-subject", scenario.title));

  const prob = el("p", "sc-prob-line", probabilityLine(scenario));
  const advice = el("p", "sc-advice", scenario.advice);
  const meta = el(
    "p",
    "ev-meta",
    [
      `${scenario.reports} report${scenario.reports === 1 ? "" : "s"}`,
      `${scenario.data_tier} evidence`,
      scenario.sample_size
        ? `${scenario.sample_size} scored outcomes behind the tier`
        : "no scored outcomes behind the tier",
    ].join(" ? "),
  );

  const grid = el("div", "ev-grid");
  const memberBox = el("section", "ev-block");
  memberBox.append(el("h2", "ev-block-title", "Member events"));
  const list = el("ul", "ev-timeline");
  for (const m of members) {
    const li = el("li");
    const a = el("a", "ev-link", m.subject);
    a.href = `/app/event/${m.id}`;
    li.append(
      a,
      el("span", "ev-type", `${m.verdict} ${m.signal_score >= 0 ? "+" : ""}${m.signal_score}`),
    );
    li.append(
      el(
        "time",
        "ev-time",
        m.timestamp ? new Date(m.timestamp).toUTCString() : "time not recorded",
      ),
    );
    // A sibling of the link, never inside it: the two actions stay separate.
    const hide = el("button", "story-toggle", "Hide and recompute");
    hide.type = "button";
    hide.setAttribute("aria-label", `Hide event ${m.id} and recompute the scenario`);
    hide.onclick = () => {
      hide.disabled = true;
      apply(m.id).catch(() => {
        hide.disabled = false;
        hide.textContent = "Recompute failed - try again";
      });
    };
    li.append(hide);
    list.append(li);
  }
  if (!list.childElementCount)
    list.append(el("li", "empty", "No member rows are still in the window."));
  memberBox.append(list);
  grid.append(
    memberBox,
    legs(scenario.sectors, "Sector tilt"),
    legs(scenario.exposure, "Exposed tickers"),
    historyBlock(detail),
  );

  const facts = el(
    "p",
    "ev-note",
    `Window: the last ${window.event_cap} analysed events over ${window.lookback_days} days (${window.events_considered} considered). A scenario is one instruction from many stories; the member list is the evidence behind it.`,
  );
  page.append(back, head, prob, advice, meta);
  if (whatIf) page.append(whatIfStrip(whatIf, restore));
  page.append(grid, facts);
  return page;
}

export class ScenarioPageView {
  readonly el: HTMLElement;

  constructor() {
    this.el = el("div", "ev-host");
    this.el.hidden = true;
  }

  async load(id: string): Promise<void> {
    this.el.hidden = false;
    this.el.replaceChildren(el("p", "empty", "Loading scenario..."));
    try {
      const detail = (await api.scenario(id)) as ScenarioDetail;
      this.el.replaceChildren(renderScenarioPage(detail));
    } catch {
      const box = el("div", "event-page");
      const back = el("a", "ev-back", "Back to the dashboard");
      back.href = DASHBOARD;
      box.append(
        back,
        el("h1", "ev-subject", `Scenario ${id} is not available`),
        el("p", "empty", "It has left the window or the API could not be reached."),
      );
      this.el.replaceChildren(box);
    }
  }

  hide(): void {
    this.el.hidden = true;
  }
}
