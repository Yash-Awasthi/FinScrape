export function escapeHtml(s: string): string {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
}

export function signed(n: number): string {
  return `${n >= 0 ? "+" : ""}${n}`;
}

/** Compact relative age ("4m", "3h", "2d"). Null/unparseable input reads "never". */
export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "never";
  const secs = Math.max(0, Math.round((now - then) / 1000));
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  if (secs < 86_400) return `${Math.floor(secs / 3600)}h`;
  return `${Math.floor(secs / 86_400)}d`;
}

// "world/bbc_world:mainstream" -> "bbc_world", "gdelt/reuters.com:wire" -> "reuters.com".
export function sourceLabel(tag: string): string {
  return tag.replace(/:[a-z]+$/, "").replace(/^[^/]+\//, "");
}
