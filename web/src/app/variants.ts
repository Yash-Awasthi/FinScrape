// The dashboard is ONE page. Panels tile the 12-column grid band by band in
// this exact order — deterministic, no variants, no freeform dragging.
//
// Every band sums to 12, and every panel the app registers appears exactly once:
// a slot naming a panel that does not exist renders nothing, and a panel missing
// from this list is built, wired and then hidden by `applyVariant`. Both failure
// modes are silent, so `layout.test.ts` asserts the two sets match.

export interface PanelSlot {
  id: string;
  w: number;
  h: number;
}

export const PAGE_LAYOUT: PanelSlot[] = [
  // band 1 — live markets + watchlist
  { id: "markets-live", w: 8, h: 6 },
  { id: "watchlist", w: 4, h: 6 },
  // band 2 — the advice itself: clustered scenarios and what each one implies.
  // Above the evidence panels on purpose; the rest of the page is why it says so.
  { id: "scenarios", w: 12, h: 7 },
  // band 3 — intelligence: signals + globe
  { id: "feed", w: 4, h: 8 },
  { id: "globe", w: 8, h: 8 },
  // band 4 — chart + research (both re-aim on worldfin:select-symbol)
  { id: "candles", w: 8, h: 6 },
  { id: "agents", w: 4, h: 6 },
  // band 5 — state of the world. `suggestions` reports per-ticker mention counts,
  // which is all the old `markets` panel showed.
  { id: "stats", w: 4, h: 4 },
  { id: "sectors", w: 4, h: 4 },
  { id: "suggestions", w: 4, h: 4 },
  // band 6 — the news room. The lobby tabs every registry feed, so a panel pinned
  // to one of them (`worldnews`) was showing a subset of this.
  { id: "lobby", w: 12, h: 8 },
  // band 7 — broadcast, full width: one player and a channel rail
  { id: "livetv", w: 12, h: 6 },
  // band 8 — proof: corroboration, realized accuracy, ingest health
  { id: "correlations", w: 4, h: 4 },
  { id: "accuracy", w: 4, h: 4 },
  { id: "sources", w: 4, h: 4 },
  // band 9 — forward-looking + social
  { id: "prediction", w: 6, h: 5 },
  { id: "sentiment", w: 6, h: 5 },
  // band 10 — date strip
  { id: "calendar", w: 12, h: 5 },
];

export function pagePanelIds(): Set<string> {
  return new Set(PAGE_LAYOUT.map((p) => p.id));
}
