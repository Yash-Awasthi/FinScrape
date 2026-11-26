// Chrome copy for the two interface languages. Explicit semantic keys, no regex:
// every string that gets swapped is named here, and apply.ts maps it back exactly.

export type Lang = "en" | "hi";

export interface ChromeCopy {
  tabToday: string;
  tabDesk: string;
  tabTickers: string;
  tabRecord: string;
  tabSources: string;
  refresh: string;
  refreshTitle: string;
  tabs: string;
  connConnecting: string;
  connOpen: string;
  connClosed: string;
  palette: string;
  loading: string;
  feedEmpty: string;
  disclaimer: string;
  toggle: string;
  toggleAria: string;
}

export const EN: ChromeCopy = {
  tabToday: "Today",
  tabDesk: "My Desk",
  tabTickers: "Tickers",
  tabRecord: "Track record",
  tabSources: "Sources",
  refresh: "Refresh feed and panels",
  refreshTitle: "refresh",
  tabs: "views",
  connConnecting: "realtime connecting",
  connOpen: "realtime open",
  connClosed: "realtime closed",
  palette: "chart XOM · or search events…",
  loading: "Loading…",
  feedEmpty: "No signals yet.",
  disclaimer: "Not financial advice.",
  toggle: "हिं",
  toggleAria: "Switch to Hindi",
};

export const HI: ChromeCopy = {
  tabToday: "आज",
  tabDesk: "मेरा डेस्क",
  tabTickers: "टिकर",
  tabRecord: "ट्रैक रिकॉर्ड",
  tabSources: "स्रोत",
  refresh: "फ़ीड और पैनल रीफ़्रेश करें",
  refreshTitle: "फ़ीड और पैनल रीफ़्रेश करें",
  tabs: "दृश्य",
  connConnecting: "रीयलटाइम जुड़ रहा है",
  connOpen: "रीयलटाइम चालू",
  connClosed: "रीयलटाइम बंद",
  palette: "सिंबल चार्ट करें · या ईवेंट खोजें…",
  loading: "लोड हो रहा है…",
  feedEmpty: "अभी कोई संकेत नहीं।",
  disclaimer: "यह वित्तीय सलाह नहीं है।",
  toggle: "EN",
  toggleAria: "अंग्रेज़ी में बदलें",
};

/** Nav link order and the copy key each `data-view` carries. */
export const TABS: ReadonlyArray<{
  view: "today" | "desk" | "tickers" | "record" | "sources";
  key: keyof ChromeCopy;
}> = [
  { view: "today", key: "tabToday" },
  { view: "desk", key: "tabDesk" },
  { view: "tickers", key: "tabTickers" },
  { view: "record", key: "tabRecord" },
  { view: "sources", key: "tabSources" },
];

export const LANG_KEY = "finscrape.lang";
