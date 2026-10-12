// Inline-SVG chart primitives.
//
// No charting library: the whole app bundle is ~49 kB gzipped and Chart.js alone
// would more than double it for a handful of small figures. Each helper returns an
// SVG string sized by viewBox, so it scales to whatever the panel gives it.
//
// Every figure carries role="img" + aria-label — a chart nobody can read is not
// information, and these sit beside the numbers they summarise, never replacing them.

const UP = "#16c784";
const DOWN = "#ea3943";
const MUTED = "#8a8f98";

/** Colour for a signed value: green up, red down, grey flat. */
export function signColor(n: number): string {
  if (n > 0) return UP;
  if (n < 0) return DOWN;
  return MUTED;
}

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
}

/**
 * Line through `values`, scaled to its own range. Flat or single-point input draws nothing.
 *
 * `fromZero` anchors the scale at the origin, which is what counts want. Prices do not:
 * a 200-dollar stock moving 2 dollars is a flat line against a zero baseline, so pass
 * false and let the series fill its own band.
 */
export function sparkline(values: number[], label = "trend", stroke = UP, fromZero = true): string {
  if (values.length < 2) return "";
  const w = 240;
  const h = 48;
  const min = fromZero ? Math.min(...values, 0) : Math.min(...values);
  const max = fromZero ? Math.max(...values, 0) : Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((y, i) => {
      const x = (i / (values.length - 1)) * w;
      return `${x.toFixed(1)},${(h - ((y - min) / span) * h).toFixed(1)}`;
    })
    .join(" ");
  return (
    `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" ` +
    `role="img" aria-label="${esc(label)}: ${values.length} points, ${min} to ${max}">` +
    `<polyline points="${pts}" fill="none" stroke="${stroke}" stroke-width="2"/></svg>`
  );
}

export interface Bar {
  label: string;
  value: number;
  color?: string;
  note?: string;
}

/** Horizontal bars sharing one scale — the shape for ranked categorical counts. */
export function barChart(bars: Bar[], label = "breakdown"): string {
  if (!bars.length) return "";
  const max = Math.max(1, ...bars.map((b) => Math.abs(b.value)));
  const rows = bars
    .map((b) => {
      const pct = Math.round((Math.abs(b.value) / max) * 100);
      return (
        `<div class="vz-row"><span class="vz-label" title="${esc(b.label)}">${esc(b.label)}</span>` +
        `<span class="vz-track"><i style="width:${pct}%;background:${b.color ?? UP}"></i></span>` +
        `<span class="vz-val">${esc(b.note ?? String(b.value))}</span></div>`
      );
    })
    .join("");
  return `<div class="vz-bars" role="img" aria-label="${esc(label)}">${rows}</div>`;
}

/** Vertical columns — daily volume and other evenly-spaced series. */
export function columns(values: number[], label = "volume", onPick?: string): string {
  if (!values.length) return "";
  const max = Math.max(1, ...values);
  const cols = values
    .map((v, i) => {
      const pct = Math.max(2, Math.round((v / max) * 100));
      const pick = onPick ? ` data-${onPick}="${i}"` : "";
      return `<i class="vz-col" style="height:${pct}%"${pick} title="${v}"></i>`;
    })
    .join("");
  return (
    `<div class="vz-cols" role="img" aria-label="${esc(label)}: ` +
    `${values.length} buckets, peak ${max}">${cols}</div>`
  );
}

/** One bar split into proportional segments — parts of a whole, in place. */
export function stackedBar(segments: { value: number; color: string; label: string }[]): string {
  const total = segments.reduce((a, s) => a + s.value, 0);
  if (total <= 0) return "";
  const parts = segments
    .filter((s) => s.value > 0)
    .map(
      (s) =>
        `<i style="width:${(s.value / total) * 100}%;background:${s.color}" ` +
        `title="${esc(s.label)}: ${s.value}"></i>`,
    )
    .join("");
  const aria = segments.map((s) => `${s.label} ${s.value}`).join(", ");
  return `<div class="vz-stack" role="img" aria-label="${esc(aria)}">${parts}</div>`;
}

export interface CalPoint {
  /** Predicted probability the bucket stands for — its midpoint. */
  predicted: number;
  /** Observed hit rate in that bucket. */
  observed: number;
  /** Evidence behind the point; drives dot size so thin buckets read as thin. */
  weight: number;
  label: string;
}

/**
 * Calibration curve: observed hit rate against predicted confidence, over the
 * perfect-calibration diagonal. Points above the line are underconfident, below it
 * overconfident — the one thing a reliability table makes you compute in your head.
 */
export function calibration(points: CalPoint[], label = "calibration"): string {
  const usable = points
    .filter((p) => Number.isFinite(p.observed) && Number.isFinite(p.predicted))
    .sort((a, b) => a.predicted - b.predicted);
  if (!usable.length) return "";
  const size = 160;
  const pad = 12;
  const span = size - pad * 2;
  const x = (v: number): number => pad + Math.min(1, Math.max(0, v)) * span;
  const y = (v: number): number => size - pad - Math.min(1, Math.max(0, v)) * span;
  const maxWeight = Math.max(...usable.map((p) => p.weight), 1);

  const path = usable
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.predicted).toFixed(1)},${y(p.observed).toFixed(1)}`)
    .join(" ");
  const dots = usable
    .map((p) => {
      const r = 2.5 + 3 * Math.sqrt(p.weight / maxWeight);
      const color = p.observed >= p.predicted ? UP : DOWN;
      return (
        `<circle cx="${x(p.predicted).toFixed(1)}" cy="${y(p.observed).toFixed(1)}" ` +
        `r="${r.toFixed(1)}" fill="${color}"><title>${esc(p.label)}: ` +
        `${Math.round(p.observed * 100)}% observed vs ${Math.round(p.predicted * 100)}% ` +
        `predicted, weight ${p.weight}</title></circle>`
      );
    })
    .join("");
  const aria = usable
    .map(
      (p) =>
        `${p.label} predicted ${Math.round(p.predicted * 100)}% observed ${Math.round(p.observed * 100)}%`,
    )
    .join(", ");

  return (
    `<svg class="vz-cal" viewBox="0 0 ${size} ${size}" role="img" ` +
    `aria-label="${esc(label)}: ${aria}">` +
    `<rect x="${pad}" y="${pad}" width="${span}" height="${span}" fill="none" ` +
    `stroke="${MUTED}" stroke-opacity="0.3"/>` +
    `<line x1="${pad}" y1="${size - pad}" x2="${size - pad}" y2="${pad}" ` +
    `stroke="${MUTED}" stroke-dasharray="4 3" stroke-opacity="0.6"/>` +
    (usable.length > 1
      ? `<path d="${path}" fill="none" stroke="${MUTED}" stroke-width="1.5"/>`
      : "") +
    dots +
    `</svg>`
  );
}

export const VIZ_COLORS = { up: UP, down: DOWN, muted: MUTED };
