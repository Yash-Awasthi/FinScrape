// Swaps the chrome strings of the running shell between English and Hindi.
// The surface is an explicit allowlist: nav tabs, their label, refresh, the connection
// dot, the palette placeholder, the two panel placeholders, the disclaimer's leading
// sentence, and the toggle itself. Analysis text is never touched.

import { EN, HI, LANG_KEY, TABS, type ChromeCopy, type Lang } from "./hi";

const DICT: Record<Lang, ChromeCopy> = { en: EN, hi: HI };
const CONN_KEYS = ["connConnecting", "connOpen", "connClosed"] as const;

/** Writes only on change, which keeps the observer quiet and every apply idempotent. */
function setText(el: Element, value: string): void {
  if (el.textContent !== value) el.textContent = value;
}

function setAttr(el: Element, name: string, value: string): void {
  if (el.getAttribute(name) !== value) el.setAttribute(name, value);
}

function safeStorage(win: Window | null | undefined): Storage | null {
  try {
    return win?.localStorage ?? null;
  } catch {
    // A blocked storage must not break the page; the toggle still works for the tab.
    return null;
  }
}

export function resolveLanguage(search: string, storage: Storage | null): Lang {
  const param = new URLSearchParams(search).get("lang");
  if (param === "hi" || param === "en") return param;
  try {
    const stored = storage?.getItem(LANG_KEY);
    if (stored === "hi" || stored === "en") return stored;
  } catch {
    // Ignore an unreadable storage and fall through to the default.
  }
  return "en";
}

const wired = new WeakSet<HTMLElement>();

function ensureToggle(doc: Document): HTMLElement | null {
  const right = doc.querySelector(".head-right");
  if (!right) return null;
  const existing = right.querySelector<HTMLElement>(".lang-toggle");
  if (existing) return existing;
  const button = doc.createElement("button");
  button.className = "lang-toggle";
  button.type = "button";
  right.append(button);
  return button;
}

function wireToggle(button: HTMLElement, doc: Document): void {
  if (wired.has(button)) return;
  wired.add(button);
  button.addEventListener("click", () => {
    const next: Lang = doc.documentElement.lang === "hi" ? "en" : "hi";
    try {
      safeStorage(doc.defaultView)?.setItem(LANG_KEY, next);
    } catch {
      // The preference just will not survive a reload.
    }
    applyLanguage(next, doc);
  });
}

export function applyLanguage(lang: Lang, doc: Document = document): void {
  const dict = DICT[lang];
  const from = DICT[lang === "hi" ? "en" : "hi"];
  doc.documentElement.lang = lang;

  const nav = doc.querySelector("nav.tabs");
  if (nav) {
    setAttr(nav, "aria-label", dict.tabs);
    for (const tab of TABS) {
      const link = nav.querySelector(`a[data-view="${tab.view}"]`);
      if (link) setText(link, dict[tab.key]);
    }
  }

  const refresh = doc.querySelector(".refresh");
  if (refresh) {
    setAttr(refresh, "aria-label", dict.refresh);
    setAttr(refresh, "title", dict.refreshTitle);
  }

  const dot = doc.querySelector(".conn-dot");
  if (dot) {
    const label = dot.getAttribute("aria-label");
    for (const key of CONN_KEYS) {
      if (label === from[key]) {
        setAttr(dot, "aria-label", dict[key]);
        break;
      }
    }
  }

  const input = doc.querySelector(".palette input");
  if (input) setAttr(input, "placeholder", dict.palette);

  for (const el of doc.querySelectorAll('.panel-body > .empty[aria-busy="true"]')) {
    if (el.textContent === from.loading) setText(el, dict.loading);
  }
  for (const el of doc.querySelectorAll(".panel-body > .empty")) {
    if (el.textContent === from.feedEmpty) setText(el, dict.feedEmpty);
  }

  // The disclaimer carries a surface caveat after the shared sentence; keep it byte
  // for byte and only swap the leading sentence.
  for (const p of doc.querySelectorAll("p.disclaimer")) {
    const text = p.textContent ?? "";
    if (text.startsWith(from.disclaimer)) {
      setText(p, dict.disclaimer + text.slice(from.disclaimer.length));
    }
  }

  const toggle = ensureToggle(doc);
  if (toggle) {
    wireToggle(toggle, doc);
    setText(toggle, dict.toggle);
    setAttr(toggle, "aria-label", dict.toggleAria);
  }
}

export function applyHindi(doc: Document = document): void {
  applyLanguage("hi", doc);
}

export function applyEnglish(doc: Document = document): void {
  applyLanguage("en", doc);
}

export function install(doc: Document = document, win: Window = window): () => void {
  applyLanguage(resolveLanguage(win.location.search, safeStorage(win)), doc);
  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => {
      scheduled = false;
      applyLanguage(doc.documentElement.lang === "hi" ? "hi" : "en", doc);
    });
  });
  if (doc.body) {
    observer.observe(doc.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["aria-label", "title", "placeholder"],
    });
  }
  return () => observer.disconnect();
}

// The browser entry self-starts; vitest imports the module for its API only.
if (typeof document !== "undefined" && import.meta.env.MODE !== "test") install();
