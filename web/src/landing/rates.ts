// Rate labels for the landing page. A rate without n, a window and an interval is a
// claim the record cannot support (plan m1.4.3), so these builders carry all three.
// They live here, not in landing.ts, so the rule is testable without a DOM.

export interface Rate {
  scored: number;
  hit_rate: number;
  sample?: string;
  ci95?: [number, number] | null;
}

export interface AccuracyLike extends Rate {
  window?: { from: string | null; to: string | null };
  vs_spy?: Partial<Record<"d2" | "d4", Rate>>;
}

/** The span the scored calls cover, so a rate is never quoted without a date range. */
export function windowLabel(window?: { from: string | null; to: string | null }): string {
  if (!window?.from) return "no scored calls yet";
  return `${window.from.slice(0, 10)} to ${window.to?.slice(0, 10) ?? "now"}`;
}

/** `<n>, <interval>` — falls back to a bare `n=` when the API sent no sample string. */
export function sampleLabel(rate: Rate): string {
  return rate.sample ?? `n=${rate.scored}`;
}

/** Headline hit-rate value: the rate only once the sample can carry it, else the count. */
export function hitValue(acc: AccuracyLike, minSample = 30): string {
  return acc.scored >= minSample ? `${Math.round(acc.hit_rate * 100)}%` : String(acc.scored);
}

/** The label under the headline rate: n, interval, window and what the number means. */
export function hitLabel(acc: AccuracyLike, minSample = 30): string {
  const span = windowLabel(acc.window);
  if (acc.scored < minSample) {
    return `calls scored so far against realized moves · ${span} · no rate until ${minSample}`;
  }
  return (
    `next day: ${sampleLabel(acc)} · ${span} · ` +
    "share of INVEST/PULL_OUT calls whose ticker moved the way called"
  );
}

/** The +4-day-vs-SPY label, carrying n and interval for both horizons. */
export function spyLabel(spy: Partial<Record<"d2" | "d4", Rate>>): string {
  const d4 = spy.d4 ?? { scored: 0, hit_rate: 0 };
  const d2 = spy.d2 ?? { scored: 0, hit_rate: 0 };
  return `+4 days vs SPY: ${sampleLabel(d4)} (+2 days: ${sampleLabel(d2)})`;
}
