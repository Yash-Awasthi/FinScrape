import { beforeEach, expect, it, vi } from "vite-plus/test";

import {
  DEFAULT_STATE,
  decodeState,
  encodeState,
  FILTER_EVENT,
  installPermalinks,
  normalizeState,
  permalinkFor,
  readState,
  writeState,
} from "./permalink";

beforeEach(() => {
  window.history.replaceState(null, "", "/app/");
  document.body.replaceChildren();
});

it("round-trips a full state through the query string", () => {
  const state = {
    view: "tickers" as const,
    verdict: "INVEST",
    sector: "energy,shipping",
    ticker: "XOM",
    topic: "Hormuz",
    minScore: 6,
    q: "tanker",
    page: 3,
  };
  const search = encodeState(state);
  expect(search).toBe(
    "?view=tickers&verdict=INVEST&sector=energy%2Cshipping&ticker=XOM&topic=Hormuz&minScore=6&q=tanker&page=3",
  );
  expect(decodeState(search)).toEqual(state);
});

it("encodes the same state to the same string whatever order it was built in", () => {
  const a = { view: "desk" as const, ticker: "XOM", sector: "energy" };
  const b = { sector: "energy", view: "desk" as const, ticker: "XOM" };
  expect(encodeState(a)).toBe(encodeState(b));
  expect(encodeState(a)).toBe("?view=desk&sector=energy&ticker=XOM");
});

it("omits every default", () => {
  expect(encodeState(DEFAULT_STATE)).toBe("");
  expect(encodeState({})).toBe("");
  expect(decodeState("")).toEqual(DEFAULT_STATE);
});

it("tolerates garbage: bad view, bad numbers, unsplit noise", () => {
  const state = decodeState(
    "?view=nowhere&minScore=abc&page=-3&ticker=%20%2C%20XOM%20%2C%2C%20XOM&q=%20%20",
  );
  expect(state.view).toBe("today");
  expect(state.minScore).toBeNull();
  expect(state.page).toBe(1);
  expect(state.ticker).toBe("XOM");
  expect(state.q).toBe("");
  // Unknown parameters are ignored instead of echoed into the next link.
  expect(encodeState(decodeState("?utm_source=x&verdict=INVEST"))).toBe("?verdict=INVEST");
});

it("rejects a minScore or page outside its range", () => {
  expect(normalizeState({ minScore: 101 }).minScore).toBeNull();
  expect(normalizeState({ minScore: -1 }).minScore).toBeNull();
  expect(normalizeState({ page: 0 }).page).toBe(1);
  expect(normalizeState({ page: 2 }).page).toBe(2);
});

it("writes the URL without reloading the page", () => {
  document.body.dataset.boot = "kept";
  const spy = vi.spyOn(window.history, "replaceState");
  const target = writeState({ view: "record", ticker: "XOM" });

  expect(spy).toHaveBeenCalledTimes(1);
  expect(target).toBe("/app/?view=record&ticker=XOM");
  expect(window.location.pathname).toBe("/app/");
  expect(window.location.search).toBe("?view=record&ticker=XOM");
  // A reload would have rebuilt the DOM; the boot marker survives.
  expect(document.body.dataset.boot).toBe("kept");
  expect(readState().view).toBe("record");
  spy.mockRestore();
});

it("keeps a partial write from dropping the rest of the state", () => {
  window.history.replaceState(null, "", "/app/?view=desk&sector=energy");
  writeState({ ticker: "XOM" });
  expect(readState()).toMatchObject({
    view: "desk",
    sector: "energy",
    ticker: "XOM",
  });
});

it("installPermalinks boots from the URL and follows filter changes", () => {
  window.history.replaceState(null, "", "/app/?view=tickers&ticker=XOM&hash-not-used#tickers");
  const boot = installPermalinks();
  expect(boot.view).toBe("tickers");
  expect(boot.ticker).toBe("XOM");

  window.dispatchEvent(new CustomEvent(FILTER_EVENT, { detail: { sector: "energy", page: 2 } }));
  expect(window.location.search).toBe("?view=tickers&sector=energy&ticker=XOM&page=2");
  expect(window.location.hash).toBe("#tickers");
});

it("permalinkFor returns an absolute link", () => {
  const link = permalinkFor({ view: "sources", topic: "shipping" });
  expect(link).toBe(`${window.location.origin}/?view=sources&topic=shipping`);
});
