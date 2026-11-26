// Permalinks: the query string is the filter state, so any filtered view is a URL.
//
// `encodeState` writes a stable query (fixed key order, defaults omitted) so the same
// view always produces the same link; `decodeState` never trusts the URL and falls back
// to the default view rather than rendering an empty page. `writeState` uses
// `history.replaceState`, so changing a filter never reloads the dashboard.

export const VIEWS = ["today", "desk", "tickers", "record", "sources"] as const;
export type ViewId = (typeof VIEWS)[number];

export interface FilterState {
  view: ViewId;
  verdict: string;
  sector: string;
  ticker: string;
  topic: string;
  minScore: number | null;
  q: string;
  page: number;
}

export const DEFAULT_STATE: FilterState = {
  view: "today",
  verdict: "",
  sector: "",
  ticker: "",
  topic: "",
  minScore: null,
  q: "",
  page: 1,
};

/** The event a panel dispatches when a filter changes: detail is a partial state. */
export const FILTER_EVENT = "worldfin:filters-changed";

const LIST_FIELDS = ["verdict", "sector", "ticker", "topic"] as const;
// The one order in the query string. Insertion order is the sort order.
const KEY_ORDER = [
  "view",
  "verdict",
  "sector",
  "ticker",
  "topic",
  "minScore",
  "q",
  "page",
] as const;

function isView(value: string): value is ViewId {
  return (VIEWS as readonly string[]).includes(value);
}

/** Comma lists are trimmed, de-duplicated and re-joined: "energy, ,tech" -> "energy,tech". */
function listOf(raw: string | null | undefined): string {
  if (!raw) return "";
  const seen = new Set<string>();
  for (const part of raw.split(",")) {
    const value = part.trim();
    if (value) seen.add(value);
  }
  return [...seen].join(",");
}

function numberIn(raw: string | null | undefined, min: number, max: number): number | null {
  if (raw === null || raw === undefined || raw.trim() === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  const rounded = Math.floor(value);
  if (rounded < min || rounded > max) return null;
  return rounded;
}

export function normalizeState(partial: Partial<FilterState>): FilterState {
  const state: FilterState = { ...DEFAULT_STATE, ...partial };
  const minScore =
    state.minScore === null || state.minScore === undefined
      ? null
      : numberIn(String(state.minScore), 0, 100);
  const page = numberIn(String(state.page), 1, Number.MAX_SAFE_INTEGER) ?? 1;
  return {
    view: isView(state.view) ? state.view : DEFAULT_STATE.view,
    verdict: listOf(state.verdict),
    sector: listOf(state.sector),
    ticker: listOf(state.ticker),
    topic: listOf(state.topic),
    minScore,
    q: (state.q ?? "").trim(),
    page,
  };
}

/** The query string for a state, defaults omitted, keys in one fixed order. */
export function encodeState(partial: Partial<FilterState>): string {
  const state = normalizeState(partial);
  const params = new URLSearchParams();
  for (const key of KEY_ORDER) {
    const value = state[key];
    if (key === "view" && value === DEFAULT_STATE.view) continue;
    if (key === "minScore" && value === null) continue;
    if (key === "page" && value === 1) continue;
    if (typeof value === "string" && value === "") continue;
    params.set(key, String(value));
  }
  const search = params.toString();
  return search ? `?${search}` : "";
}

/** A validated state from a query string; garbage is dropped, never rendered. */
export function decodeState(search: string): FilterState {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const view = params.get("view") ?? "";
  const lists = Object.fromEntries(
    LIST_FIELDS.map((key) => [key, listOf(params.get(key))]),
  ) as Pick<FilterState, (typeof LIST_FIELDS)[number]>;
  return normalizeState({
    view: isView(view) ? view : DEFAULT_STATE.view,
    ...lists,
    minScore: numberIn(params.get("minScore"), 0, 100),
    q: params.get("q") ?? "",
    page: numberIn(params.get("page"), 1, Number.MAX_SAFE_INTEGER) ?? 1,
  });
}

export function readState(): FilterState {
  return decodeState(window.location.search);
}

/** Merge a partial state into the current URL without a reload. Returns the new URL. */
export function writeState(partial: Partial<FilterState>): string {
  const next = normalizeState({ ...readState(), ...partial });
  const target = `${window.location.pathname}${encodeState(next)}${window.location.hash}`;
  window.history.replaceState(null, "", target);
  return target;
}

/** An absolute link for a state, so a filter can be shared as-is. */
export function permalinkFor(partial: Partial<FilterState>, path = "/"): string {
  const origin = window.location.origin === "null" ? "" : window.location.origin;
  return `${origin}${path}${encodeState(partial)}`;
}

let installed = false;

/**
 * Mount the link: returns the state the URL booted with (the shell shows that view) and
 * keeps the query string in step with `FILTER_EVENT` from any panel.
 */
export function installPermalinks(): FilterState {
  if (!installed) {
    installed = true;
    window.addEventListener(FILTER_EVENT, (event) => {
      const detail = (event as CustomEvent<Partial<FilterState>>).detail;
      if (detail) writeState(detail);
    });
  }
  return readState();
}
