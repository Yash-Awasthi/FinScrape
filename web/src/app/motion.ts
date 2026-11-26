import "./motion.css";

export const VIEW_CHANGE_MS = 150;
export const ARRIVAL_MS = 180;

export function reducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function animateViewChange(el: HTMLElement, fromView: string | null, toView: string): void {
  // First paint is not a view change.
  if (fromView === null || fromView === toView) return;
  if (reducedMotion()) return;
  if (typeof el.animate !== "function") return;
  el.animate(
    [
      { opacity: 0.6, transform: "translateY(4px)" },
      { opacity: 1, transform: "none" },
    ],
    { duration: VIEW_CHANGE_MS, easing: "ease-out" },
  );
}

export function newArrivalIds(
  events: Array<{ id: number }>,
  seen: ReadonlySet<number>,
): Set<number> {
  const out = new Set<number>();
  // The first render is a load, not an arrival.
  if (seen.size === 0) return out;
  for (const e of events) if (!seen.has(e.id)) out.add(e.id);
  return out;
}
