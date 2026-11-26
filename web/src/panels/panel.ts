// Panel base: a titled grid cell with a debounced body.
// Deterministic layout — position comes from the variant's panel order and the
// panel's declared span; no freeform dragging or persisted overrides.

import { markArrivals } from "./arrivals";

import { errorNotice, skeleton } from "../components/view-state";

export interface PanelConfig {
  id: string;
  title: string;
  w: number; // column span (of the 12-col grid)
  h: number; // row span
}

export class Panel {
  readonly el: HTMLElement;
  readonly body: HTMLElement;
  readonly cfg: PanelConfig;
  private pending: number | null = null;
  private seen = new Set<number>();

  constructor(defaults: PanelConfig) {
    this.cfg = defaults;

    this.el = document.createElement("section");
    this.el.className = "panel";
    this.el.dataset.id = this.cfg.id;

    const header = document.createElement("header");
    header.className = "panel-head";
    header.textContent = this.cfg.title;

    this.body = document.createElement("div");
    this.body.className = "panel-body";
    // Replaced by the first setContent; a panel whose load never lands still shows the skeleton.
    this.body.innerHTML = skeleton(2);

    this.el.append(header, this.body);
    this.applyGrid();
  }

  applyGrid(): void {
    const { w, h } = this.cfg;
    this.el.style.gridColumn = `span ${Math.min(w, 12)}`;
    this.el.style.gridRow = `span ${h}`;
  }

  /** Debounced so rapid live updates coalesce into one paint. */
  setContent(node: Node | string): void {
    if (this.pending !== null) cancelAnimationFrame(this.pending);
    this.pending = requestAnimationFrame(() => {
      this.body.replaceChildren();
      if (typeof node === "string") this.body.innerHTML = node;
      else this.append(node);
      // Only the live feed appends events between paints; every other body swaps wholesale.
      if (this.cfg.id === "feed") markArrivals(this.body, this.seen);
      this.pending = null;
    });
  }

  private append(node: Node): void {
    this.body.append(node);
  }

  /**
   * A failed refresh keeps the last good content and puts a retry strip above it,
   * so a transient error never blanks a panel the reader was already reading.
   */
  showError(message: string, retry?: () => void): void {
    this.body.querySelector(".state-error")?.remove();
    this.body.prepend(errorNotice(message, retry, `retry-${this.cfg.id}`));
  }

  /** A successful load removes the retry strip. */
  clearError(): void {
    this.body.querySelector(".state-error")?.remove();
  }
}
