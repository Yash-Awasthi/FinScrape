// Follow-a-thing, backed by /api/watchlists (plan m4.1.2).
//
// Writes need the ingest API key. The dashboard is served from the same origin as the
// API, but the key is a deployment secret, so the browser never receives it implicitly:
// the user pastes it once into the My Desk panel and it lives in localStorage. Reads
// need no key at all.

import { API_BASE, type FollowKind, type Watchlist, type WatchlistItem } from "./api";

const KEY_STORAGE = "worldfin.apiKey";

/** The starter lists the empty state offers, so a first tap is not a blank field. */
export const STARTERS: Record<string, Array<{ kind: FollowKind; value: string }>> = {
  Energy: [
    { kind: "sector", value: "energy" },
    { kind: "ticker", value: "XOM" },
    { kind: "topic", value: "shipping" },
  ],
  Rates: [
    { kind: "sector", value: "rates" },
    { kind: "ticker", value: "TLT" },
    { kind: "topic", value: "monetary" },
  ],
  Shipping: [
    { kind: "topic", value: "shipping" },
    { kind: "sector", value: "shipping" },
    { kind: "region", value: "Hormuz" },
  ],
};

export function apiKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return ""; // private mode / disabled storage: the panel explains what to do
  }
}

export function setApiKey(key: string): void {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    // storage unavailable; the next write will still fail visibly
  }
}

async function write<T>(method: string, path: string, body?: unknown): Promise<T> {
  const key = apiKey();
  if (!key) throw new Error("no API key: add it in My Desk to save follows");
  const res = await fetch(API_BASE + path, {
    method,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-API-Key": key,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) throw new Error("the API key was rejected");
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export async function desk(createIfMissing = false): Promise<Watchlist | null> {
  const { api } = await import("./api");
  const lists = await api.watchlists();
  const existing = lists[0] ?? null;
  if (existing || !createIfMissing) return existing;
  const created = await write<{ watchlist: Watchlist }>("POST", "/api/watchlists", {
    name: "My Desk",
    items: [],
  });
  return created.watchlist;
}

/** Follow one kind/value on the first list (creating "My Desk" on the first follow). */
export async function follow(kind: FollowKind, value: string): Promise<Watchlist> {
  const list = (await desk(true)) as Watchlist;
  // `follow` is idempotent server-side: an existing item comes back instead of a 409.
  await write<{ item: WatchlistItem }>("POST", `/api/watchlists/${list.id}/items`, {
    kind,
    value,
  });
  const refreshed = await desk();
  window.dispatchEvent(new CustomEvent("worldfin:followed", { detail: { kind, value } }));
  return refreshed ?? list;
}

export async function unfollow(listId: number, itemId: number): Promise<void> {
  await write<{ ok: boolean }>("DELETE", `/api/watchlists/${listId}/items/${itemId}`);
  window.dispatchEvent(new CustomEvent("worldfin:followed", { detail: null }));
}

export async function createStarter(name: string): Promise<Watchlist> {
  const created = await write<{ watchlist: Watchlist }>("POST", "/api/watchlists", {
    name,
    items: STARTERS[name] ?? [],
  });
  window.dispatchEvent(new CustomEvent("worldfin:followed", { detail: null }));
  return created.watchlist;
}
