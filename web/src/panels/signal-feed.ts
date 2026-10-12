// SignalFeedPanel: analyzed intelligence — verdicts, scores, reasoning preview,
// and the source article link. Compact rows with verdict filters.
//
// A5: rows that belong to the same storyline (embedding cluster: same story
// from several sources within a 48h window) collapse under their top row as a
// "+N sources" expander, so five syndicated copies stop becoming five rows.

import { type EventOut, type Storyline, verdictColor } from "../api";
import { escapeHtml, timeAgo } from "../util";
import { Panel } from "./panel";

export class SignalFeedPanel extends Panel {
  private verdictFilter = "ALL";
  private sectorFilter = "";
  private sourceFilter = "";
  // Survives re-renders: a live WS push must not silently drop your selection.
  private activeId: number | null = null;
  private lastEvents: EventOut[] = [];
  // Storylines the user opened stay open across re-renders (WS pushes, filters).
  private readonly expanded = new Set<number>();

  constructor(private readonly onSelect: (e: EventOut) => void) {
    super({ id: "feed", title: "Signal Feed — analyzed events", w: 5, h: 9 });
    // Sector Heat chips re-aim the feed; clicking the active chip again clears it.
    window.addEventListener("worldfin:select-sector", (e) => {
      const sector = (e as CustomEvent<string>).detail;
      if (!sector) return;
      this.sectorFilter = this.sectorFilter === sector ? "" : sector;
      this.update(this.lastEvents);
    });
    // Source Health rows do the same, so a failing or noisy feed can be isolated.
    window.addEventListener("worldfin:select-source", (e) => {
      const source = (e as CustomEvent<string>).detail;
      if (!source) return;
      this.sourceFilter = this.sourceFilter === source ? "" : source;
      this.update(this.lastEvents);
    });
  }

  /** Rows currently rendered and visible, in feed order — what j/k walks. */
  private navigableRows(): HTMLTableRowElement[] {
    return [...this.body.querySelectorAll<HTMLTableRowElement>("table.feed tbody tr")].filter(
      (tr) => !tr.classList.contains("story-expand") && !tr.classList.contains("hidden"),
    );
  }

  clearActive(): void {
    this.activeId = null;
    for (const tr of this.navigableRows()) tr.classList.remove("active");
  }

  private markActive(tr: HTMLTableRowElement, id: number): void {
    for (const row of this.navigableRows()) row.classList.remove("active");
    tr.classList.add("active");
    this.activeId = id;
  }

  /** Move the selection by `delta` rows and select it — the row IS the selection, so
   *  reading down the feed needs one key, not a key plus Enter. */
  moveSelection(delta: number): void {
    const rows = this.navigableRows();
    if (!rows.length) return;
    const at = rows.findIndex((tr) => tr.classList.contains("active"));
    // First press enters at the top going down, at the bottom going up.
    const next = at === -1 ? (delta > 0 ? 0 : rows.length - 1) : at + delta;
    const target = rows[Math.max(0, Math.min(rows.length - 1, next))];
    const id = Number(target.dataset.eventId);
    this.markActive(target, id);
    target.scrollIntoView({ block: "nearest" });
    const event = this.lastEvents.find((e) => e.id === id);
    if (event) this.onSelect(event);
  }

  update(events: EventOut[]): void {
    this.lastEvents = events;
    if (!events.length) {
      this.setContent('<p class="empty">No signals yet.</p>');
      return;
    }
    const verdicts = ["ALL", ...new Set(events.map((e) => e.verdict))];
    const wrap = document.createElement("div");
    wrap.innerHTML =
      `<div class="feed-filters">` +
      (this.sectorFilter
        ? `<button class="ffilter sector active" data-sector="${escapeHtml(this.sectorFilter)}" title="clear sector filter">⚡ ${escapeHtml(this.sectorFilter)} ✕</button>`
        : "") +
      (this.sourceFilter
        ? `<button class="ffilter sector active" data-source="${escapeHtml(this.sourceFilter)}" title="clear source filter">📡 ${escapeHtml(this.sourceFilter)} ✕</button>`
        : "") +
      verdicts
        .map(
          (v) =>
            `<button class="ffilter${v === this.verdictFilter ? " active" : ""}" data-v="${v}">${v}</button>`,
        )
        .join("") +
      `</div>`;
    wrap.addEventListener("click", (e) => {
      const sectorBtn = (e.target as HTMLElement).closest<HTMLElement>("[data-sector]");
      if (sectorBtn) {
        this.sectorFilter = "";
        this.update(this.lastEvents);
        return;
      }
      const sourceBtn = (e.target as HTMLElement).closest<HTMLElement>("[data-source]");
      if (sourceBtn) {
        this.sourceFilter = "";
        this.update(this.lastEvents);
        return;
      }
      const v = (e.target as HTMLElement).closest<HTMLElement>(".ffilter")?.dataset.v;
      if (v) {
        this.verdictFilter = v;
        this.update(this.lastEvents);
      }
    });
    wrap.append(this.buildTable(events));
    this.setContent(wrap);
  }

  private buildTable(events: EventOut[]): HTMLTableElement {
    const table = document.createElement("table");
    table.className = "feed compact";
    table.innerHTML = "<thead><tr><th>Signal</th></tr></thead>";
    const tbody = document.createElement("tbody");
    const matchesSector = (e: EventOut): boolean =>
      e.sector === this.sectorFilter ||
      (e.sector_impact ?? "").split(/[/,]/).some((s) => s.trim() === this.sectorFilter);
    const filtered =
      this.verdictFilter === "ALL"
        ? events
        : events.filter((e) => e.verdict === this.verdictFilter);
    const bySector = this.sectorFilter ? filtered.filter(matchesSector) : filtered;
    const shown = this.sourceFilter
      ? bySector.filter((e) => (e.sources ?? []).includes(this.sourceFilter))
      : bySector;

    if (!shown.length) {
      const lens = this.sourceFilter || this.sectorFilter || this.verdictFilter;
      tbody.innerHTML = `<tr><td class="empty">No signals in ${escapeHtml(lens)}.</td></tr>`;
      table.append(tbody);
      return table;
    }

    // ── storyline collapse ───────────────────────────────────────────────────
    // Only the unfiltered default view collapses (filters show exact rows: a
    // verdict/sector lens on one story should still list every match). For each
    // multi-member cluster we pick the member that comes first in feed order as
    // the lead row and hide the rest behind its expander — never hide a row
    // whose lead isn't in this view (stale cache or day-scoped load).
    const storylines = window.__wfStorylines ?? [];
    const collapse = this.verdictFilter === "ALL" && !this.sectorFilter && !this.sourceFilter;
    const leadOf = new Map<number, Storyline>(); // lead event id → cluster
    const hideIds = new Set<number>(); // member ids rendered under their lead
    if (collapse) {
      const order = new Map(shown.map((e, i) => [e.id, i]));
      const present = new Set(shown.map((e) => e.id));
      for (const cl of storylines) {
        if (cl.size < 2) continue;
        const members = cl.members.filter((m) => present.has(m.id));
        if (members.length < 2) continue;
        const lead = members.reduce((a, b) =>
          (order.get(b.id) ?? Infinity) < (order.get(a.id) ?? Infinity) ? b : a,
        );
        leadOf.set(lead.id, cl);
        for (const m of members) if (m.id !== lead.id) hideIds.add(m.id);
      }
    }

    const byId = new Map(shown.map((e) => [e.id, e]));
    const othersOf = (cl: Storyline, leadId: number): EventOut[] =>
      cl.members.filter((m) => m.id !== leadId && byId.has(m.id)).map((m) => byId.get(m.id)!);

    let rendered = 0; // lead rows count toward the 60-row cap
    for (const e of shown) {
      if (rendered >= 60) break;
      if (hideIds.has(e.id)) continue;
      tbody.append(this.rowFor(e));
      rendered += 1;
      const cl = leadOf.get(e.id);
      if (!cl) continue;
      const others = othersOf(cl, e.id);
      const open = this.expanded.has(e.id);
      tbody.append(this.expanderRow(e.id, others, open));
      const openClass = open ? "" : " hidden";
      for (const m of others) {
        const tr = this.rowFor(m);
        tr.className = `story-member${openClass}`;
        tbody.append(tr);
      }
    }
    table.append(tbody);
    return table;
  }

  /** One signal row (also used for storylines' collapsed member rows). */
  private rowFor(e: EventOut): HTMLTableRowElement {
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    tr.dataset.eventId = String(e.id); // j/k resolves the row back to its event
    if (e.id === this.activeId) tr.classList.add("active");
    const link = e.articles?.[0];
    const subject = link
      ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener" title="open source article">${escapeHtml(e.subject)}</a>`
      : escapeHtml(e.subject);
    const reasoning = e.reasoning
      ? `<div class="row-reasoning">${escapeHtml(e.reasoning.slice(0, 110))}${e.reasoning.length > 110 ? "…" : ""}</div>`
      : "";
    const surging = (window.__wfSuggestions ?? []).filter((s) => e.tickers.includes(s.ticker));
    const badge = surging.length
      ? `<span class="momentum-badge" title="${escapeHtml(surging.map((s) => s.ticker).join(", "))} in top suggestions">🔥</span>`
      : "";
    const nOrder = (e.second_order_effects ?? []).filter(Boolean).length;
    const chainBadge = nOrder
      ? `<span class="chain-badge" title="${nOrder} second-order effect${nOrder > 1 ? "s" : ""} — open the signal to see the chain">→${nOrder}</span>`
      : "";
    tr.innerHTML =
      `<td><span class="dot" style="background:${verdictColor(e.verdict)}"></span>` +
      `${e.verdict} <b>${e.signal_score >= 0 ? "+" : ""}${e.signal_score}</b>` +
      `<span class="row-meta">${badge}${chainBadge}${Math.round(e.confidence * 100)}% · ${escapeHtml(e.tickers.slice(0, 4).join(", ")) || "—"}` +
      ` · ${timeAgo(e.timestamp)} · ${e.sources.length} src${e.divergence_flag ? ' · <span class="warn" title="the model and the text disagree on direction">divergent</span>' : ""}</span>` +
      `<div class="subj">${subject}</div>${reasoning}</td>`;
    tr.addEventListener("click", () => {
      // Text selection means the user is copying, not clicking. Otherwise the whole
      // row selects — including the headline link, which still opens the article in
      // its own tab, so a click can never land on a row and select nothing.
      if (window.getSelection()?.toString()) return;
      this.markActive(tr, e.id); // j/k continues from wherever the click landed
      this.onSelect(e);
    });
    return tr;
  }

  /** "+N sources" expander shown under a storyline's lead row. */
  private expanderRow(leadId: number, others: EventOut[], open: boolean): HTMLTableRowElement {
    const tr = document.createElement("tr");
    tr.className = "story-expand";
    const td = document.createElement("td");
    const btn = document.createElement("button");
    const sources = new Set<string>();
    for (const m of others) for (const s of m.sources ?? []) sources.add(s);
    const n = sources.size || others.length;
    const label = sources.size
      ? [...sources].slice(0, 4).join(", ")
      : others.map((m) => m.subject).join(" · ");
    btn.textContent = `${open ? "▾" : "▸"} +${n} source${n === 1 ? "" : "s"}`;
    btn.title =
      others.length === 1
        ? "same story, one more source"
        : `same story from ${others.length} more rows — ${label}${sources.size > 4 ? "…" : ""}`;
    btn.className = "story-toggle";
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (open) this.expanded.delete(leadId);
      else this.expanded.add(leadId);
      this.update(this.lastEvents); // re-render: toggles .story-member visibility
    });
    td.append(btn);
    tr.append(td);
    return tr;
  }
}
