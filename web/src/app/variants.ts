// The dashboard has four views. Each tiles the 12-column grid band by band in the
// order listed; every band sums to 12 and every registered panel sits in exactly one
// view. `layout.test.ts` asserts both, because a mistake hides a panel silently.

export interface PanelSlot {
  id: string;
  w: number;
  h: number;
}

export type ViewId = "today" | "tickers" | "record" | "sources";

export const VIEWS: Record<ViewId, { label: string; slots: PanelSlot[] }> = {
  today: {
    label: "Today",
    slots: [
      // The advice first; everything under it is the evidence.
      { id: "scenarios", w: 12, h: 6 },
      { id: "feed", w: 5, h: 9 },
      { id: "globe", w: 7, h: 9 },
      { id: "stats", w: 4, h: 4 },
      { id: "calendar", w: 8, h: 4 },
    ],
  },
  tickers: {
    label: "Tickers",
    slots: [
      { id: "suggestions", w: 4, h: 9 },
      { id: "candles", w: 8, h: 9 },
      { id: "sectors", w: 12, h: 5 },
    ],
  },
  record: {
    label: "Track record",
    slots: [
      { id: "accuracy", w: 6, h: 7 },
      { id: "prediction", w: 6, h: 7 },
      { id: "outcomes", w: 12, h: 8 },
    ],
  },
  sources: {
    label: "Sources",
    slots: [
      { id: "sources", w: 6, h: 8 },
      { id: "correlations", w: 6, h: 8 },
    ],
  },
};

export function isView(id: string): id is ViewId {
  return id in VIEWS;
}

export function allPanelIds(): string[] {
  return Object.values(VIEWS).flatMap((v) => v.slots.map((s) => s.id));
}
