// One primary action per view; the rest live in an overflow menu. A view that shows
// every action as a button makes the safe path and the rare path look equally
// important, so the primary is a single button and the menu is behind one control.

export interface Action {
  label: string;
  run: () => void;
  /** Tooltip and, when label is a glyph, the accessible name. */
  title?: string;
  /** Extra classes, for call sites that already style a control (e.g. "refresh"). */
  className?: string;
}

export interface ActionSpec {
  /** The one visible action for this view. */
  primary: Action;
  /** Everything else, in the overflow menu. */
  secondary: Action[];
}

/** Build the action bar: one primary button, then a details-based overflow menu. */
export function actionBar(spec: ActionSpec): HTMLElement {
  const bar = document.createElement("div");
  bar.className = "action-bar";

  const primary = document.createElement("button");
  primary.type = "button";
  primary.className = `btn-primary action-primary${spec.primary.className ? " " + spec.primary.className : ""}`;
  primary.dataset.primary = "true";
  primary.textContent = spec.primary.label;
  primary.title = spec.primary.title ?? spec.primary.label;
  primary.setAttribute("aria-label", spec.primary.title ?? spec.primary.label);
  primary.addEventListener("click", spec.primary.run);
  bar.append(primary);

  if (!spec.secondary.length) return bar;

  const menu = document.createElement("details");
  menu.className = "action-overflow";
  const summary = document.createElement("summary");
  summary.setAttribute("aria-label", "More actions");
  summary.title = "More actions";
  summary.textContent = "\u22ee";
  menu.append(summary);

  const list = document.createElement("div");
  list.className = "action-menu";
  for (const action of spec.secondary) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "action-secondary";
    button.textContent = action.label;
    button.title = action.title ?? action.label;
    button.addEventListener("click", () => {
      menu.open = false;
      action.run();
    });
    list.append(button);
  }
  menu.append(list);
  bar.append(menu);

  // A click anywhere else closes the menu; Esc closes it too.
  document.addEventListener("click", (e) => {
    if (menu.open && !menu.contains(e.target as Node)) menu.open = false;
  });
  bar.addEventListener("keydown", (e) => {
    if (e.key === "Escape") menu.open = false;
  });

  return bar;
}
