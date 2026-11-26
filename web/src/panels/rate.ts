// A rate below the minimum sample is a claim the record cannot carry (plan m5.3.2).
// Every dashboard rate goes through here so "67%" and "insufficient sample" can never
// disagree about what n is enough.

export const MIN_SAMPLE = 20;

/** True when a rate may be shown as a number at all. */
export function hasSample(n: number | null | undefined): boolean {
  return n != null && n >= MIN_SAMPLE;
}

/** The percentage once n can carry it, else the literal the plan asks for. */
export function rateText(n: number | null | undefined, rate: number | null | undefined): string {
  if (rate == null || !hasSample(n)) return "insufficient sample";
  return `${Math.round(rate * 100)}%`;
}
