// Pure helpers for the PWA layer. Kept free of DOM and service-worker globals so
// vitest can exercise the cache and banner rules directly.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const OFFLINE_TEXT = "Offline - showing cached events";

export interface EventLike {
  id: number;
}

/** Newest 200 by id, returned newest-first (the API's own order, and the order the
 *  feed renders; it caps the visible rows, so the newest must come first). */
export function trimEvents<P extends { events: EventLike[] }>(payload: P, max = 200): P {
  const events = [...payload.events]
    .sort((a, b) => a.id - b.id)
    .slice(-max)
    .reverse();
  return { ...payload, events } as P;
}

/** The list endpoint only; /api/events/12 is one row and must not be trimmed. */
export function isEventsApiRequest(url: string): boolean {
  try {
    return new URL(url, "https://finscrape.invalid").pathname === "/api/events";
  } catch {
    return false;
  }
}

/** Runtime-cacheable: plain same-origin GETs that are not API data or the worker. */
export function isCacheableAsset(url: string, method: string, hasAuth: boolean): boolean {
  if (method.toUpperCase() !== "GET" || hasAuth) return false;
  let pathname: string;
  try {
    pathname = new URL(url, "https://finscrape.invalid").pathname;
  } catch {
    return false;
  }
  if (pathname === "/sw.js") return false;
  return !pathname.startsWith("/api/");
}

/** "26 Nov 2026, 10:04 UTC" - fixed UTC so the banner reads the same everywhere. */
export function formatCachedAt(ms: number): string {
  const d = new Date(ms);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${hh}:${mm} UTC`;
}

/** Banner copy. Empty string means nothing to show (online). */
export function bannerText(cachedAt: number | null, online: boolean): string {
  if (online) return "";
  if (cachedAt == null) return OFFLINE_TEXT;
  return `${OFFLINE_TEXT} (cached ${formatCachedAt(cachedAt)})`;
}
