// Service worker for the FinScrape dashboard at /app/.
//
// Three behaviours, all versioned so a deploy can drop the old caches:
//   - app shell: precached on install, network-first navigation with an offline fallback
//   - /api/events: network-first, the newest 200 rows cached with a timestamp
//   - same-origin static assets: runtime cache
// Non-GET, credentialed requests and other /api routes are never cached.

const VERSION = "v1";
const SHELL_CACHE = `finscrape-shell-${VERSION}`;
const RUNTIME_CACHE = `finscrape-runtime-${VERSION}`;
const EVENTS_CACHE = `finscrape-events-${VERSION}`;
const CURRENT_CACHES = [SHELL_CACHE, RUNTIME_CACHE, EVENTS_CACHE];
const CACHE_PREFIX = "finscrape-";

const OFFLINE_URL = "/app/";
const PRECACHE_URLS = ["/app/", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

const EVENTS_PATH = "/api/events";
const META_PATH = "/__pwa_meta__";
const MAX_EVENTS = 200;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && !CURRENT_CACHES.includes(key))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

function jsonResponse(body) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

// Newest 200 by id. The API returns newest-first and the feed renders in array
// order (it shows the first 60 rows), so the cache keeps that same newest-first
// order after dropping the oldest rows from the ascending payload.
function trimEvents(payload, max) {
  const events = Array.isArray(payload && payload.events) ? payload.events : [];
  const trimmed = [...events]
    .sort((a, b) => a.id - b.id)
    .slice(-max)
    .reverse();
  return Object.assign({}, payload, { events: trimmed });
}

async function networkFirstEvents(request) {
  const cache = await caches.open(EVENTS_CACHE);
  const key = new Request(new URL(EVENTS_PATH, self.location.origin));
  try {
    const res = await fetch(request);
    if (!res.ok) return res;
    let trimmed = null;
    try {
      trimmed = trimEvents(await res.clone().json(), MAX_EVENTS);
    } catch {
      return res;
    }
    const body = jsonResponse(trimmed);
    await cache.put(key, body.clone());
    await cache.put(
      new Request(new URL(META_PATH, self.location.origin)),
      jsonResponse({ cachedAt: Date.now() }),
    );
    return body;
  } catch {
    const hit = (await cache.match(key)) || (await cache.match(request));
    return hit || jsonResponse({ events: [] });
  }
}

async function networkFirstNavigation(request) {
  try {
    return await fetch(request);
  } catch {
    const shell = await caches.open(SHELL_CACHE);
    return (
      (await shell.match(request)) ||
      (await shell.match(OFFLINE_URL)) ||
      (await caches.match(OFFLINE_URL)) ||
      Response.error()
    );
  }
}

async function runtimeAsset(request) {
  const hit = await caches.match(request);
  if (hit) return hit;
  try {
    const res = await fetch(request);
    if (res.ok && res.type === "basic") {
      const cache = await caches.open(RUNTIME_CACHE);
      await cache.put(request, res.clone());
    }
    return res;
  } catch {
    return Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  if (request.headers.get("Authorization")) return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname === EVENTS_PATH) {
    event.respondWith(networkFirstEvents(request));
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(networkFirstNavigation(request));
    return;
  }
  // Only the events feed is cached from the API; bars are never served stale.
  if (url.pathname.startsWith("/api/")) return;
  if (url.pathname === "/sw.js") return;

  event.respondWith(runtimeAsset(request));
});
