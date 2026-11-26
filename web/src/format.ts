// Metric number formatting: one fixed precision and unit per kind, so a value reads
// the same in a tile, a table and a chart tick. Tabular figures are a CSS concern
// (.num); this module owns the text.

export type Metric =
  | "score"
  | "percent"
  | "change"
  | "price"
  | "points"
  | "fx"
  | "count"
  | "ratio"
  | "tokens"
  | "seconds"
  | "brier";

interface Spec {
  decimals: number;
  unit: string;
  signed: boolean;
  /** Some units attach without a space (%, :1); words take one. */
  tight: boolean;
}

export const METRICS: Record<Metric, Spec> = {
  score: { decimals: 0, unit: "", signed: true, tight: true },
  percent: { decimals: 1, unit: "%", signed: false, tight: true },
  change: { decimals: 2, unit: "%", signed: true, tight: true },
  price: { decimals: 2, unit: "USD", signed: false, tight: false },
  points: { decimals: 2, unit: "pts", signed: false, tight: false },
  fx: { decimals: 4, unit: "", signed: false, tight: true },
  count: { decimals: 0, unit: "", signed: false, tight: true },
  ratio: { decimals: 1, unit: ":1", signed: false, tight: true },
  tokens: { decimals: 0, unit: "tokens", signed: false, tight: false },
  seconds: { decimals: 1, unit: "s", signed: false, tight: true },
  brier: { decimals: 3, unit: "", signed: false, tight: true },
};

/** Fixed decimals and an explicit unit, or an em dash for a missing value. */
export function formatMetric(kind: Metric, value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const spec = METRICS[kind];
  const sign = spec.signed && value > 0 ? "+" : "";
  const text = value.toLocaleString(undefined, {
    minimumFractionDigits: spec.decimals,
    maximumFractionDigits: spec.decimals,
  });
  if (!spec.unit) return `${sign}${text}`;
  return `${sign}${text}${spec.tight ? "" : " "}${spec.unit}`;
}

/** The same text in a tabular-figure slot, so columns line up. */
export function numberCell(kind: Metric, value: number | null | undefined): string {
  return `<span class="num">${formatMetric(kind, value)}</span>`;
}
