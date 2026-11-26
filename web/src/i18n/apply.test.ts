import { beforeEach, expect, it } from "vite-plus/test";

import { applyEnglish, applyHindi, install } from "./apply";
import { EN, HI, type ChromeCopy } from "./hi";

const KEYS: Array<keyof ChromeCopy> = [
  "tabToday",
  "tabDesk",
  "tabTickers",
  "tabRecord",
  "tabSources",
  "refresh",
  "refreshTitle",
  "tabs",
  "connConnecting",
  "connOpen",
  "connClosed",
  "palette",
  "loading",
  "feedEmpty",
  "disclaimer",
  "toggle",
  "toggleAria",
];

const VIEW_LABELS: Array<[string, string]> = [
  ["today", "Today"],
  ["desk", "My Desk"],
  ["tickers", "Tickers"],
  ["record", "Track record"],
  ["sources", "Sources"],
];

const TAB_KEYS: Array<[string, keyof ChromeCopy]> = [
  ["today", "tabToday"],
  ["desk", "tabDesk"],
  ["tickers", "tabTickers"],
  ["record", "tabRecord"],
  ["sources", "tabSources"],
];

/** The chrome the shell ships, plus analysis text that must survive untouched. */
function buildShell(doc: Document = document): void {
  const nav = doc.createElement("nav");
  nav.className = "tabs";
  nav.setAttribute("aria-label", "views");
  for (const [view, label] of VIEW_LABELS) {
    const a = doc.createElement("a");
    a.dataset.view = view;
    a.textContent = label;
    nav.append(a);
  }

  const dot = doc.createElement("span");
  dot.className = "conn-dot";
  dot.setAttribute("aria-label", "realtime open");
  dot.title = "realtime connection";

  const refresh = doc.createElement("button");
  refresh.className = "refresh";
  refresh.setAttribute("aria-label", "Refresh feed and panels");
  refresh.title = "refresh";

  const right = doc.createElement("div");
  right.className = "head-right";
  right.append(doc.createElement("time"), dot, refresh);

  const palette = doc.createElement("div");
  palette.className = "palette hidden";
  const input = doc.createElement("input");
  input.placeholder = "chart XOM · or search events…";
  palette.append(input);

  const body = doc.createElement("div");
  body.className = "panel-body";
  const loading = doc.createElement("p");
  loading.className = "empty";
  loading.setAttribute("aria-busy", "true");
  loading.textContent = "Loading…";
  const feedEmpty = doc.createElement("p");
  feedEmpty.className = "empty";
  feedEmpty.textContent = "No signals yet.";
  body.append(loading, feedEmpty);

  const disclaimer = doc.createElement("p");
  disclaimer.className = "disclaimer";
  disclaimer.textContent = "Not financial advice. Research and education only.";

  const subj = doc.createElement("div");
  subj.className = "subj";
  subj.textContent = "Today the refresh feed and panels ... Loading…";

  const reasoning = doc.createElement("div");
  reasoning.className = "row-reasoning";
  reasoning.textContent =
    "Realtime open, no signals yet. Loading… means the panel is still fetching.";

  doc.body.append(nav, right, palette, body, disclaimer, subj, reasoning);
}

function text(doc: Document, selector: string): string {
  return doc.querySelector(selector)?.textContent ?? "";
}

function attr(doc: Document, selector: string, name: string): string {
  return doc.querySelector(selector)?.getAttribute(name) ?? "";
}

function snapshot(doc: Document = document): string[] {
  return [
    ...VIEW_LABELS.map(([view]) => text(doc, `nav.tabs a[data-view="${view}"]`)),
    attr(doc, "nav.tabs", "aria-label"),
    attr(doc, ".refresh", "aria-label"),
    attr(doc, ".refresh", "title"),
    attr(doc, ".conn-dot", "aria-label"),
    attr(doc, ".palette input", "placeholder"),
    text(doc, '.panel-body > .empty[aria-busy="true"]'),
    text(doc, ".panel-body > .empty:not([aria-busy])"),
    text(doc, "p.disclaimer"),
    text(doc, ".lang-toggle"),
    attr(doc, ".lang-toggle", "aria-label"),
    doc.documentElement.lang,
  ];
}

beforeEach(() => {
  document.body.replaceChildren();
  document.documentElement.lang = "en";
  localStorage.clear();
});

it("dictionary: every chrome key exists in both languages and Hindi is never blank", () => {
  expect(KEYS.length).toBe(17);
  for (const key of KEYS) {
    expect(typeof EN[key], key).toBe("string");
    expect(EN[key].length, key).toBeGreaterThan(0);
    expect(typeof HI[key], key).toBe("string");
    expect(HI[key].length, key).toBeGreaterThan(0);
  }
});

it("minimal shell: Hindi apply swaps every chrome string and leaves analysis text alone", () => {
  buildShell();
  const subj = text(document, ".subj");
  const reasoning = text(document, ".row-reasoning");

  applyHindi();

  for (const [view, key] of TAB_KEYS) {
    expect(text(document, `nav.tabs a[data-view="${view}"]`)).toBe(HI[key]);
  }
  expect(attr(document, "nav.tabs", "aria-label")).toBe(HI.tabs);
  expect(attr(document, ".refresh", "aria-label")).toBe(HI.refresh);
  expect(attr(document, ".refresh", "title")).toBe(HI.refreshTitle);
  expect(attr(document, ".conn-dot", "aria-label")).toBe(HI.connOpen);
  expect(attr(document, ".palette input", "placeholder")).toBe(HI.palette);
  expect(text(document, '.panel-body > .empty[aria-busy="true"]')).toBe(HI.loading);
  expect(text(document, ".panel-body > .empty:not([aria-busy])")).toBe(HI.feedEmpty);
  expect(text(document, "p.disclaimer")).toBe(`${HI.disclaimer} Research and education only.`);
  expect(document.documentElement.lang).toBe("hi");
  expect(text(document, ".subj")).toBe(subj);
  expect(text(document, ".row-reasoning")).toBe(reasoning);
});

it("toggle: clicking from Hindi restores the exact English chrome", () => {
  buildShell();
  applyHindi();
  document.querySelector<HTMLElement>(".head-right .lang-toggle")?.click();

  expect(text(document, 'nav.tabs a[data-view="today"]')).toBe("Today");
  expect(attr(document, "nav.tabs", "aria-label")).toBe("views");
  expect(attr(document, ".refresh", "aria-label")).toBe("Refresh feed and panels");
  expect(attr(document, ".refresh", "title")).toBe("refresh");
  expect(attr(document, ".conn-dot", "aria-label")).toBe("realtime open");
  expect(attr(document, ".palette input", "placeholder")).toBe("chart XOM · or search events…");
  expect(text(document, '.panel-body > .empty[aria-busy="true"]')).toBe("Loading…");
  expect(text(document, ".panel-body > .empty:not([aria-busy])")).toBe("No signals yet.");
  expect(text(document, "p.disclaimer")).toBe("Not financial advice. Research and education only.");
  expect(document.documentElement.lang).toBe("en");
  expect(text(document, ".lang-toggle")).toBe("हिं");
});

it("persistence: the toggle saves the mode and install() picks it up on a fresh shell", () => {
  buildShell();
  applyEnglish();
  document.querySelector<HTMLElement>(".head-right .lang-toggle")?.click();
  expect(localStorage.getItem("finscrape.lang")).toBe("hi");

  document.body.replaceChildren();
  buildShell();
  const stop = install(document);
  try {
    expect(text(document, 'nav.tabs a[data-view="today"]')).toBe("आज");
    expect(document.documentElement.lang).toBe("hi");
  } finally {
    stop();
  }
});

it("idempotent: a second apply in either mode changes nothing", () => {
  buildShell();

  applyHindi();
  const hindi = snapshot();
  applyHindi();
  expect(snapshot()).toEqual(hindi);

  applyEnglish();
  const english = snapshot();
  applyEnglish();
  expect(snapshot()).toEqual(english);
});
