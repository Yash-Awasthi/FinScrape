import { beforeEach, describe, expect, it } from "vite-plus/test";

import { NO_FILTERS, filterSearch, hasFilters, readFilters, writeFilters } from "./url-filters";

const LONG = "x".repeat(65);

describe("url filters", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("a clean address reads as no filters and writes nothing", () => {
    expect(filterSearch(NO_FILTERS)).toBe("");
    expect(readFilters("")).toEqual(NO_FILTERS);
  });

  it("roundtrips every lens through the query string", () => {
    const f = { verdict: "BUY", sector: "energy", source: "world_rss", topic: "oil" };
    const search = filterSearch(f);
    expect(readFilters(search)).toEqual(f);
    expect(search).toContain("v=BUY");
    expect(search).toContain("sector=energy");
    expect(search).toContain("source=world_rss");
    expect(search).toContain("topic=oil");
    expect([...new URLSearchParams(search).keys()].sort()).toEqual([
      "sector",
      "source",
      "topic",
      "v",
    ]);
  });

  it("omits default values from the address", () => {
    expect(filterSearch({ ...NO_FILTERS, sector: "tech" })).toBe("?sector=tech");
  });

  it("drops a value longer than the cap", () => {
    expect(readFilters(`?sector=${LONG}`)).toEqual(NO_FILTERS);
  });

  it("reads whitespace as unset and falls back to ALL", () => {
    expect(readFilters("?sector=%20%20")).toEqual(NO_FILTERS);
    expect(readFilters("?v=").verdict).toBe("ALL");
  });

  it("knows when any lens is on", () => {
    expect(hasFilters(NO_FILTERS)).toBe(false);
    expect(hasFilters({ ...NO_FILTERS, verdict: "BUY" })).toBe(true);
    expect(hasFilters({ ...NO_FILTERS, sector: "energy" })).toBe(true);
    expect(hasFilters({ ...NO_FILTERS, source: "gdelt" })).toBe(true);
    expect(hasFilters({ ...NO_FILTERS, topic: "oil" })).toBe(true);
  });

  it("writes the address bar without a history entry", () => {
    const f = { verdict: "INVEST", sector: "", source: "gdelt", topic: "" };
    writeFilters(f);
    expect(window.location.search).toBe(filterSearch(f));
    writeFilters(NO_FILTERS);
    expect(window.location.search).toBe("");
  });
});
