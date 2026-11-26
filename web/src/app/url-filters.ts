// Filters live in the URL, so a reload or a shared link lands on the same lens.
// Only non-default values are written: the unfiltered feed keeps a clean address.

export interface Filters {
  verdict: string; // "ALL" when unset
  sector: string;
  source: string;
  topic: string;
}

export const NO_FILTERS: Filters = { verdict: "ALL", sector: "", source: "", topic: "" };

const KEYS: Record<keyof Filters, string> = {
  verdict: "v",
  sector: "sector",
  source: "source",
  topic: "topic",
};

/** Cap on a filter value: longer than any real verdict/sector/topic/source name. */
const MAX = 64;

function clean(value: string | null): string {
  const text = (value ?? "").trim();
  return text.length > MAX ? "" : text;
}

/** Read the four lens values out of a query string; unknown keys are ignored. */
export function readFilters(search: string): Filters {
  const q = new URLSearchParams(search);
  const verdict = clean(q.get(KEYS.verdict));
  return {
    verdict: verdict || "ALL",
    sector: clean(q.get(KEYS.sector)),
    source: clean(q.get(KEYS.source)),
    topic: clean(q.get(KEYS.topic)),
  };
}

export function hasFilters(f: Filters): boolean {
  return f.verdict !== "ALL" || !!f.sector || !!f.source || !!f.topic;
}

/** The query string for these filters, without the leading "?" when default. */
export function filterSearch(f: Filters): string {
  const q = new URLSearchParams();
  if (f.verdict !== "ALL") q.set(KEYS.verdict, f.verdict);
  if (f.sector) q.set(KEYS.sector, f.sector);
  if (f.source) q.set(KEYS.source, f.source);
  if (f.topic) q.set(KEYS.topic, f.topic);
  const out = q.toString();
  return out ? `?${out}` : "";
}

/**
 * Put the filters in the address bar without adding a history entry, so Back still
 * leaves the view instead of walking through every chip the reader tried.
 */
export function writeFilters(f: Filters, url: URL = new URL(window.location.href)): void {
  if (typeof window === "undefined" || !window.history?.replaceState) return;
  window.history.replaceState(null, "", url.pathname + filterSearch(f) + url.hash);
}
