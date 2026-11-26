// PWA bootstrap for the dashboard: manifest link, service-worker registration and
// the offline stale banner in the shell's .banner-slot.
//
// Progressive: environments without serviceWorker/caches do nothing at all, so the
// dashboard keeps working exactly as before.

import { bannerText } from "./helpers";

const MANIFEST_HREF = "/manifest.webmanifest";
const META_URL = "/__pwa_meta__";
const BANNER_ATTR = "data-pwa-offline";

let cachedAt: number | null = null;
// Until the first cache read resolves the banner would flash without its timestamp;
// hold it back, then render exactly once with the full text.
let ready = false;

function ensureManifest(): void {
  if (document.querySelector('link[rel="manifest"]')) return;
  const link = document.createElement("link");
  link.rel = "manifest";
  link.href = MANIFEST_HREF;
  document.head.append(link);
}

async function readCachedAt(): Promise<number | null> {
  try {
    const res = await caches.match(META_URL);
    if (!res) return null;
    const meta = (await res.json()) as { cachedAt?: unknown };
    return typeof meta.cachedAt === "number" ? meta.cachedAt : null;
  } catch {
    return null;
  }
}

function syncBanner(): void {
  if (!ready) return;
  const host = document.querySelector<HTMLElement>(".banner-slot");
  if (!host) return;
  const existing = host.querySelector<HTMLElement>(`[${BANNER_ATTR}]`);
  const text = bannerText(cachedAt, navigator.onLine);
  if (!text) {
    existing?.remove();
    return;
  }
  let node = existing;
  if (!node) {
    node = document.createElement("div");
    node.setAttribute(BANNER_ATTR, "");
    node.setAttribute("role", "status");
    node.style.cssText =
      "margin:10px 16px 0;padding:8px 14px;border-radius:8px;font-size:13px;" +
      "border:1px solid var(--warn);background:var(--warn-surface);color:var(--warn-text);";
    host.append(node);
  }
  node.textContent = text;
}

async function refreshCachedAt(): Promise<void> {
  cachedAt = await readCachedAt();
  ready = true;
  syncBanner();
}

function onOffline(): void {
  void refreshCachedAt();
}

function onOnline(): void {
  void refreshCachedAt();
}

function whenShellMounted(fn: () => void): void {
  if (document.querySelector(".banner-slot")) {
    fn();
    return;
  }
  // main.ts mounts the shell during its own module evaluation; poll briefly in case
  // this script is ever loaded first.
  const timer = window.setInterval(() => {
    if (!document.querySelector(".banner-slot")) return;
    window.clearInterval(timer);
    fn();
  }, 200);
  window.setTimeout(() => window.clearInterval(timer), 20_000);
}

function registerWorker(): void {
  const register = () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("service worker registration failed", err);
    });
  };
  if (document.readyState === "complete") register();
  else window.addEventListener("load", register, { once: true });
}

function start(): void {
  if (!("serviceWorker" in navigator) || !("caches" in window)) return;

  ensureManifest();
  registerWorker();
  whenShellMounted(() => {
    void refreshCachedAt();
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
  });
}

start();
