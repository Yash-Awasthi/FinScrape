// My Desk: the watchlist feed and the exposure summary (plan m4.1.2).
//
// Two panels share one fetch. The feed panel owns the list (create, follow, remove) and
// broadcasts what it loaded; the exposure panel counts how many of those rows touch each
// held symbol, labelled "exposure" on purpose — a tally of stories, never advice.

import { api, type EventOut, type Outcome, type Watchlist, verdictColor } from "../api";
import { escapeHtml, fmtPct, timeAgo } from "../util";
import { Panel } from "./panel";
import { apiKey, createStarter, desk, setApiKey, STARTERS, unfollow } from "../watchlist";
import { addPosition, positions, removePosition } from "../positions";

/** A call's day-one mark. A null move means unpriced, not a miss; a null verdict means
 *  the move was too small to call, and the row is named unscored rather than hidden. */
function callResult(o: Outcome | undefined): string {
  if (!o) return '<span class="muted" title="no scored window yet">unscored</span>';
  if (o.price_move_pct == null)
    return '<span class="muted" title="still waiting on a price">open</span>';
  const mark = o.correct == null ? "·" : o.correct ? "✓" : "✗";
  const cls = o.correct == null ? "muted" : o.correct ? "up" : "down";
  return `<span class="${cls}">${mark} ${fmtPct(o.price_move_pct)}</span>`;
}

export class DeskPanel extends Panel {
  private list: Watchlist | null = null;
  private error = "";
  private busy = false;
  // Outcome rows keyed by event: the scoring state behind each desk story.
  private outcomes = new Map<number, Outcome>();
  // A rejected position entry says so where the form is, not on another panel.
  private positionError = "";

  constructor(private readonly onSelect: (e: EventOut) => void) {
    super({ id: "desk", title: "My Desk — followed stories", w: 8, h: 9 });
    window.addEventListener("worldfin:followed", () => void this.load());
  }

  async load(): Promise<void> {
    try {
      this.list = await desk(false);
      this.error = "";
    } catch (err) {
      this.error = err instanceof Error ? err.message : "could not load watchlists";
    }
    if (this.list) {
      try {
        const events = await api.watchlistFeed(this.list.id, 200);
        (window as unknown as { __wfDeskEvents?: EventOut[] }).__wfDeskEvents = events;
        window.dispatchEvent(new CustomEvent("worldfin:desk-events", { detail: events }));
      } catch {
        (window as unknown as { __wfDeskEvents?: EventOut[] }).__wfDeskEvents = [];
      }
      try {
        const rows = await api.outcomes({ limit: 200 });
        this.outcomes = new Map(rows.map((o) => [o.event_id, o]));
      } catch {
        this.outcomes = new Map();
      }
    }
    this.render();
  }

  private renderKeyForm(): string {
    return (
      `<form class="desk-key"><label>API key to save follows ` +
      `<input type="password" name="key" value="${escapeHtml(apiKey())}" ` +
      `placeholder="FINSCRAPE_API_KEY" autocomplete="off"></label>` +
      `<button type="submit">Save</button>` +
      `<span class="muted">stored in this browser only; reads need no key</span></form>`
    );
  }

  /** Manual positions, browser-local only (plan m4.1.3). Optional: an empty desk
   *  needs no position, and a position never changes what the feed shows. */
  private renderPositions(): string {
    const rows = positions();
    const chips = rows
      .map(
        (p) =>
          `<span class="held" data-symbol="${escapeHtml(p.symbol)}" ` +
          `title="remove ${escapeHtml(p.symbol)} from this browser">` +
          `${escapeHtml(p.symbol)} · ${p.quantity} @ ${p.cost_basis} ×</span>`,
      )
      .join("");
    return (
      `<div class="desk-positions"><div class="desk-sub">Positions — manual, this browser only</div>` +
      `<div class="held-chips">${chips || '<span class="muted">none entered</span>'}</div>` +
      `<form class="desk-position">` +
      `<input name="symbol" placeholder="symbol" autocomplete="off" size="6">` +
      `<input name="quantity" placeholder="quantity" inputmode="decimal" autocomplete="off" size="6">` +
      `<input name="cost_basis" placeholder="cost basis" inputmode="decimal" autocomplete="off" size="7">` +
      `<button type="submit">Add</button>` +
      `<span class="muted">typed by you; no live price, no valuation, not a recommendation</span>` +
      (this.positionError ? `<span class="warn">${escapeHtml(this.positionError)}</span>` : "") +
      `</form></div>`
    );
  }

  private renderEmpty(): string {
    const buttons = Object.keys(STARTERS)
      .map(
        (name) =>
          `<button class="starter" data-starter="${escapeHtml(name)}">${escapeHtml(name)}</button>`,
      )
      .join("");
    return (
      `<div class="desk-empty"><p class="empty">Nothing followed yet. A watchlist turns the ` +
      `whole feed into the handful of stories you actually trade.</p>` +
      `<p class="muted">Start with one:</p><div class="starters">${buttons}</div>` +
      this.renderPositions() +
      this.renderKeyForm() +
      `<p class="disclaimer">Following a sector or ticker does not recommend it.</p></div>`
    );
  }

  private renderList(list: Watchlist): string {
    const chips = list.items
      .map(
        (item) =>
          `<span class="followed" data-item-id="${item.id}" title="remove from ${escapeHtml(list.name)}">` +
          `${escapeHtml(item.kind)}: ${escapeHtml(item.value)} ×</span>`,
      )
      .join("");
    return (
      `<div class="desk-head"><b>${escapeHtml(list.name)}</b>` +
      `<span class="muted">${list.items.length} followed</span></div>` +
      `<div class="followed-chips">${chips || '<span class="muted">no items yet</span>'}</div>` +
      this.renderPositions() +
      this.renderKeyForm()
    );
  }

  private renderFeed(events: EventOut[]): string {
    if (!events.length) {
      return (
        `<p class="empty">No story matches this desk yet. Follow another sector, ` +
        `ticker or topic, or wait for the next cycle.</p>`
      );
    }
    const rows = events
      .slice(0, 50)
      .map(
        (e) =>
          `<tr data-event-id="${e.id}"><td>` +
          `<span class="dot" style="background:${verdictColor(e.verdict)}"></span>` +
          `${e.verdict} <b>${e.signal_score >= 0 ? "+" : ""}${e.signal_score}</b>` +
          `<div class="subj">${escapeHtml(e.subject)}</div>` +
          `<span class="row-meta">${escapeHtml(e.tickers.slice(0, 4).join(", ")) || "—"} · ` +
          `${escapeHtml(e.sector_impact || "")} · ${timeAgo(e.timestamp)}</span>` +
          `</td></tr>`,
      )
      .join("");
    return `<table class="feed desk-feed"><tbody>${rows}</tbody></table>`;
  }

  /** The desk's calls, priced or not. A call still waiting on a price is named as open,
   *  and a followed ticker with no story yet is named as unscored — never hidden. */
  private renderCalls(events: EventOut[]): string {
    const rows = events
      .slice(0, 20)
      .map((e) => {
        const o = this.outcomes.get(e.id);
        return (
          `<tr data-event-id="${e.id}"><td class="subj-cell">${escapeHtml(e.subject)}` +
          `<span class="row-meta">${escapeHtml(e.tickers.slice(0, 3).join(", ")) || "—"}</span></td>` +
          `<td>${callResult(o)}</td></tr>`
        );
      })
      .join("");
    const quiet = (this.list?.items ?? [])
      .filter((i) => i.kind === "ticker" && !events.some((e) => e.tickers.includes(i.value)))
      .map((i) => escapeHtml(i.value));
    return (
      `<div class="desk-calls"><div class="desk-sub">Calls — day one, priced or open</div>` +
      (rows
        ? `<table class="grid-table"><thead><tr><th>Call</th><th>Next day</th></tr></thead>` +
          `<tbody>${rows}</tbody></table>`
        : `<p class="muted">No followed story has been scored yet.</p>`) +
      (quiet.length
        ? `<p class="muted">Followed, no story yet (unscored): ${quiet.join(", ")}</p>`
        : "") +
      `</div>`
    );
  }

  private render(): void {
    // Listeners must sit on the markup they belong to: setContent paints on the next
    // frame, so wiring this.body straight after it would bind the previous render.
    const wrap = document.createElement("div");
    wrap.className = "desk";
    if (this.error && !this.list) {
      wrap.innerHTML = `<p class="warn">${escapeHtml(this.error)}</p>${this.renderEmpty()}`;
    } else if (!this.list) {
      wrap.innerHTML = this.renderEmpty();
    } else {
      const events = (window as unknown as { __wfDeskEvents?: EventOut[] }).__wfDeskEvents ?? [];
      wrap.innerHTML =
        this.renderList(this.list) + this.renderCalls(events) + this.renderFeed(events);
    }
    this.wire(wrap);
    this.setContent(wrap);
  }

  private wire(root: HTMLElement): void {
    const form = root.querySelector<HTMLFormElement>(".desk-key");
    form?.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const data = new FormData(form);
      const raw = data.get("key");
      setApiKey(typeof raw === "string" ? raw.trim() : "");
      this.error = "";
      void this.load();
    });
    const positionForm = root.querySelector<HTMLFormElement>(".desk-position");
    positionForm?.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const data = new FormData(positionForm);
      const rawSymbol = data.get("symbol");
      const symbol = typeof rawSymbol === "string" ? rawSymbol.trim() : "";
      // A blank field is missing, not zero: Number("") would quietly price a line at 0.
      const num = (value: FormDataEntryValue | null): number =>
        typeof value === "string" && value.trim() !== "" ? Number(value) : Number.NaN;
      const quantity = num(data.get("quantity"));
      const costBasis = num(data.get("cost_basis"));
      if (!symbol || !Number.isFinite(quantity) || !Number.isFinite(costBasis)) {
        this.positionError = "a position needs a symbol, a quantity and a cost basis";
        this.render();
        return;
      }
      this.positionError = "";
      addPosition(symbol, quantity, costBasis);
      this.render();
    });
    for (const chip of root.querySelectorAll<HTMLElement>(".held")) {
      chip.addEventListener("click", () => {
        removePosition(chip.dataset.symbol ?? "");
        this.render();
      });
    }
    for (const button of root.querySelectorAll<HTMLButtonElement>(".starter")) {
      button.addEventListener("click", () => {
        if (this.busy) return;
        this.busy = true;
        button.disabled = true;
        void createStarter(button.dataset.starter ?? "")
          .catch((err: unknown) => {
            this.error = err instanceof Error ? err.message : "could not create the list";
          })
          .finally(() => {
            this.busy = false;
            void this.load();
          });
      });
    }
    for (const chip of root.querySelectorAll<HTMLElement>(".followed")) {
      chip.addEventListener("click", () => {
        if (!this.list) return;
        const id = Number(chip.dataset.itemId);
        void unfollow(this.list.id, id).catch((err: unknown) => {
          this.error = err instanceof Error ? err.message : "could not remove the item";
          this.render();
        });
      });
    }
    for (const tr of root.querySelectorAll<HTMLTableRowElement>("tr[data-event-id]")) {
      tr.addEventListener("click", () => {
        const id = Number(tr.dataset.eventId);
        const events = (window as unknown as { __wfDeskEvents?: EventOut[] }).__wfDeskEvents ?? [];
        const event = events.find((e) => e.id === id);
        if (event) this.onSelect(event);
      });
    }
  }
}

/** Share of desk stories touching each held symbol. Exposure is a tally of stories,
 *  not a recommendation and not a position size. */
export class ExposurePanel extends Panel {
  private events: EventOut[] = [];

  constructor() {
    super({ id: "exposure", title: "Exposure — held symbols in the desk feed", w: 4, h: 9 });
    window.addEventListener("worldfin:desk-events", (event) => {
      this.update((event as CustomEvent<EventOut[]>).detail ?? []);
    });
    // The desk's position form lives in the other panel; re-measure when it saves.
    window.addEventListener("worldfin:positions", () => this.update(this.events));
  }

  update(events: EventOut[]): void {
    this.events = events;
    const held = positions().map((p) => p.symbol);
    if (!held.length) {
      this.setContent(
        `<p class="empty">Enter a position on My Desk to see how many desk stories touch it.</p>`,
      );
      return;
    }
    const counts = held.map((symbol) => ({
      symbol,
      n: events.filter((event) => event.tickers.some((ticker) => ticker.toUpperCase() === symbol))
        .length,
    }));
    const rows = counts
      .map(({ symbol, n }) => {
        const pct = Math.round((n / Math.max(events.length, 1)) * 100);
        // Every count and share carries its own label: there is no unlabelled number here.
        const note =
          `share of the ${events.length} desk stories whose tickers include ${symbol}; ` +
          `not a recommendation and not a position size`;
        return (
          `<div class="exposure-row"><span>${escapeHtml(symbol)}</span>` +
          `<span class="bar" style="width:${pct}%"></span>` +
          `<b>${n}</b><span class="muted">${pct}%</span>` +
          `<span class="exp-tag" title="${escapeHtml(note)}">exposure only</span></div>`
        );
      })
      .join("");
    this.setContent(
      `<div class="exposure">${rows}</div>` +
        `<p class="disclaimer">Exposure only: the share of followed stories whose tickers ` +
        `include each symbol you entered. This is not a recommendation and not a position size.</p>`,
    );
  }
}
