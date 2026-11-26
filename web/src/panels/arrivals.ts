import { newArrivalIds, reducedMotion } from "../app/motion";

// Marks rows that arrived since this panel's previous render with .row-new.
export function markArrivals(root: ParentNode, seen: Set<number>): void {
  const rows: Array<{ id: number; el: HTMLElement }> = [];
  for (const el of root.querySelectorAll<HTMLElement>("[data-event-id]")) {
    const id = Number(el.dataset.eventId);
    if (!Number.isSafeInteger(id)) continue;
    rows.push({ id, el });
  }
  const arrivals = newArrivalIds(rows, seen);
  // Under reduced motion the rows still render, only the entrance animation is skipped.
  if (!reducedMotion()) {
    for (const row of rows) if (arrivals.has(row.id)) row.el.classList.add("row-new");
  }
  for (const row of rows) seen.add(row.id);
}
