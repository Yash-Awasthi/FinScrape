// One chart component: a line over one labelled y axis, unit-aware ticks, and the two
// honest non-chart states. Every line figure calls this, so axis text, decimals and
// units cannot drift apart between panels. There is deliberately no second y axis:
// two scales on one frame invite a correlation the data never showed.

export interface ChartSpec {
  values: number[];
  label: string;
  /** Unit written once on the axis caption and in the accessible label. */
  unit?: string;
  /** Fixed decimals for every tick, so a scale never jumps precision. */
  decimals?: number;
  width?: number;
  height?: number;
  fromZero?: boolean;
  stroke?: string;
  /** false for inline sparklines: no axis gutter, no tick text. */
  axes?: boolean;
  /** What to do about an empty series, in the reader's words. */
  emptyHint?: string;
}

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
}

/** Round tick steps (1/2/5 x 10^n), so labels are numbers people actually use. */
export function niceTicks(min: number, max: number, count = 3): number[] {
  const span = max - min;
  if (!Number.isFinite(span) || span <= 0) return [min];
  const raw = span / Math.max(1, count - 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag;
  const first = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = first; v <= max + step / 1e6; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks.length ? ticks : [min, max];
}

/** One fixed-decimal tick. The unit is not repeated on every tick. */
export function formatTick(value: number, decimals: number): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function state(kind: "empty" | "no-data", label: string, hint: string): string {
  const text = kind === "empty" ? "no data yet" : "no data";
  return (
    `<p class="empty chart-state" data-state="${kind}" role="status">` +
    `${esc(label)}: ${text} - ${esc(hint)}</p>`
  );
}

/**
 * Draw `values` as one polyline. Fewer than two points, or a series that is all
 * zero, becomes a stated no-data block instead of a zero line that reads as a
 * measured flat result.
 */
export function chart(spec: ChartSpec): string {
  const {
    values,
    label,
    unit = "",
    decimals = 0,
    width = 240,
    height = 72,
    fromZero = true,
    stroke = "var(--chart-1)",
    axes = true,
    emptyHint = "nothing has arrived in this window yet",
  } = spec;
  if (!values.length) return state("empty", label, emptyHint);
  if (values.length < 2 || values.every((v) => v === 0)) {
    return state("no-data", label, "every point is zero, which is not the same as flat");
  }

  const min = fromZero ? Math.min(0, ...values) : Math.min(...values);
  const max = fromZero ? Math.max(0, ...values) : Math.max(...values);
  const span = max - min || 1;
  const padL = axes ? 44 : 0;
  const padR = 0;
  const padT = axes ? 4 : 0;
  const padB = axes ? 14 : 0;
  const w = width - padL - padR;
  const h = height - padT - padB;
  const x = (i: number): number => padL + (i / (values.length - 1)) * w;
  const y = (v: number): number => padT + h - ((v - min) / span) * h;
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  const ticks = axes ? niceTicks(min, max) : [];
  const grid = ticks
    .map(
      (t) =>
        `<line class="chart-grid" x1="${padL}" y1="${y(t).toFixed(1)}" ` +
        `x2="${width - padR}" y2="${y(t).toFixed(1)}"/>` +
        `<text class="chart-tick" x="${padL - 4}" y="${(y(t) + 3).toFixed(1)}" ` +
        `text-anchor="end">${esc(formatTick(t, decimals))}</text>`,
    )
    .join("");
  const caption = axes
    ? `<text class="chart-caption" x="${padL}" y="${height - 2}">` +
      `${esc(unit ? `${label} (${unit})` : label)}</text>`
    : "";

  const aria =
    `${label}${unit ? ` in ${unit}` : ""}: ${values.length} points, ` +
    `${formatTick(min, decimals)} to ${formatTick(max, decimals)}`;

  return (
    `<svg class="chart" viewBox="0 0 ${width} ${height}" ` +
    `preserveAspectRatio="none" role="img" aria-label="${esc(aria)}">` +
    (axes ? `<g data-axis="y">${grid}${caption}</g>` : "") +
    `<polyline class="chart-line" points="${pts}" fill="none" ` +
    `stroke="${stroke}" stroke-width="2"/></svg>`
  );
}
