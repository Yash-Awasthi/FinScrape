import { describe, expect, it } from "vite-plus/test";

import {
  OFFLINE_TEXT,
  bannerText,
  formatCachedAt,
  isCacheableAsset,
  isEventsApiRequest,
  trimEvents,
} from "./helpers";

const CACHED_AT = Date.UTC(2026, 10, 26, 10, 4);

function events(from: number, to: number): Array<{ id: number; subject: string }> {
  return Array.from({ length: to - from + 1 }, (_, i) => ({
    id: from + i,
    subject: `story ${from + i}`,
  }));
}

describe("trimEvents", () => {
  it("keeps the newest 200, drops the oldest five, newest first", () => {
    const payload = { events: events(1, 205) };
    const out = trimEvents(payload);
    expect(out.events).toHaveLength(200);
    expect(out.events[0].id).toBe(205);
    expect(out.events.at(-1)?.id).toBe(6);
    expect(out.events.some((e) => e.id === 1)).toBe(false);
  });

  it("keeps the newest by id even when the input arrives newest-first", () => {
    const payload = { events: events(1, 205).reverse() };
    const out = trimEvents(payload, 3);
    expect(out.events.map((e) => e.id)).toEqual([205, 204, 203]);
  });

  it("leaves a short feed intact and preserves other keys", () => {
    const out = trimEvents({ events: events(1, 2), total: 2 });
    expect(out.events.map((e) => e.id)).toEqual([2, 1]);
    expect(out.total).toBe(2);
  });
});

describe("bannerText", () => {
  it("names the cached feed without a timestamp", () => {
    expect(bannerText(null, false)).toBe(OFFLINE_TEXT);
  });

  it("appends the cached timestamp in UTC", () => {
    expect(bannerText(CACHED_AT, false)).toBe(`${OFFLINE_TEXT} (cached 26 Nov 2026, 10:04 UTC)`);
  });

  it("is empty when online, so the banner is removed", () => {
    expect(bannerText(CACHED_AT, true)).toBe("");
    expect(bannerText(null, true)).toBe("");
  });
});

describe("formatCachedAt", () => {
  it("pads hours and minutes", () => {
    expect(formatCachedAt(Date.UTC(2026, 0, 2, 3, 5))).toBe("2 Jan 2026, 03:05 UTC");
  });
});

describe("isEventsApiRequest", () => {
  it("matches the events list with or without a query", () => {
    expect(isEventsApiRequest("https://x.test/api/events?limit=200")).toBe(true);
    expect(isEventsApiRequest("/api/events")).toBe(true);
  });

  it("ignores event detail and other API routes", () => {
    expect(isEventsApiRequest("/api/events/12")).toBe(false);
    expect(isEventsApiRequest("/api/stats")).toBe(false);
  });
});

describe("isCacheableAsset", () => {
  it("allows same-origin GET assets", () => {
    expect(isCacheableAsset("/assets/app-1.js", "GET", false)).toBe(true);
    expect(isCacheableAsset("https://x.test/icon-192.png", "get", false)).toBe(true);
  });

  it("refuses non-GET and credentialed requests", () => {
    expect(isCacheableAsset("/api/events", "POST", false)).toBe(false);
    expect(isCacheableAsset("/assets/app-1.js", "GET", true)).toBe(false);
  });

  it("refuses API data and the worker script", () => {
    expect(isCacheableAsset("/api/stats", "GET", false)).toBe(false);
    expect(isCacheableAsset("/sw.js", "GET", false)).toBe(false);
  });
});
