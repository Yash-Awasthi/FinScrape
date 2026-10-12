// PanelLayoutManager: a deterministic CSS-grid host.
// A view switch shows exactly the requested panels, in that order, each
// spanning its declared w/h — no freeform dragging, no persisted overrides.

import { Panel } from "./panel";
import type { PanelSlot } from "../app/variants";

export class PanelLayoutManager {
  readonly el: HTMLElement;
  private panels = new Map<string, Panel>();

  constructor(columns = 12) {
    this.el = document.createElement("div");
    this.el.className = "panel-grid";
    this.el.style.setProperty("--cols", String(columns));
  }

  add(panel: Panel): Panel {
    this.panels.set(panel.cfg.id, panel);
    this.el.append(panel.el);
    return panel;
  }

  get(id: string): Panel | undefined {
    return this.panels.get(id);
  }

  /** Show only the listed panels — in order, spanning the exact w/h the view
   *  prescribes. Deterministic: same view, same layout, every time. */
  applyVariant(slots: PanelSlot[]): void {
    const want = new Set(slots.map((s) => s.id));
    let order = 0;
    for (const slot of slots) {
      const panel = this.panels.get(slot.id);
      if (!panel) continue;
      panel.el.style.display = "";
      panel.el.style.order = String(order++);
      panel.el.style.gridColumn = `span ${Math.min(slot.w, 12)}`;
      panel.el.style.gridRow = `span ${slot.h}`;
      panel.el.dataset.w = String(slot.w);
      panel.el.style.setProperty("--h", String(slot.h));
    }
    for (const [id, panel] of this.panels) {
      if (!want.has(id)) panel.el.style.display = "none";
    }
  }

  /** Warn about a registered panel no view shows, or a slot naming no panel. Both
   *  are silent in the UI: the panel stays display:none, or the slot renders nothing. */
  checkViews(ids: string[]): void {
    const listed = new Set(ids);
    const orphans = [...this.panels.keys()].filter((id) => !listed.has(id));
    if (orphans.length)
      console.warn(`[layout] registered panels in no view: ${orphans.join(", ")}`);
    const phantom = ids.filter((id) => !this.panels.has(id));
    if (phantom.length)
      console.warn(`[layout] views name panels that do not exist: ${phantom.join(", ")}`);
  }

  mount(parent: HTMLElement): void {
    parent.append(this.el);
  }
}
