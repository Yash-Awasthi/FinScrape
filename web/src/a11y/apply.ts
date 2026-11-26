// Progressive accessibility layer: skip link, landmarks, hidden heading, live
// regions and keyboard activation. Every step tolerates a shell that is not
// there yet, and running the installer twice changes nothing.

const STYLE_ID = "wf-a11y-style";
const SKIP_CLASS = "wf-skip";
const SR_ONLY = "wf-sr-only";

const CSS = `
.${SKIP_CLASS}{position:absolute;left:-9999px;top:auto;width:auto;height:auto;overflow:hidden;padding:8px 12px;background:var(--panel,#121621);color:var(--text-strong,#f1f3f7);border:1px solid var(--accent,#4b8ef7);border-radius:6px;text-decoration:none;z-index:9999}
.${SKIP_CLASS}:focus{left:8px;top:8px;z-index:9999;width:auto;height:auto;overflow:visible}
.${SR_ONLY}{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
`;

const NATIVE_ACTIVATORS = new Set(["button", "a", "input", "select", "textarea", "summary"]);

const installedDocs = new WeakSet<Document>();

function parseHex(value: string): [number, number, number] | null {
  const hex = value.trim().replace(/^#/, "");
  if (hex.length === 3) {
    const [r, g, b] = hex.split("");
    return [parseInt(r + r, 16), parseInt(g + g, 16), parseInt(b + b, 16)];
  }
  if (hex.length === 6) {
    return [
      parseInt(hex.slice(0, 2), 16),
      parseInt(hex.slice(2, 4), 16),
      parseInt(hex.slice(4, 6), 16),
    ];
  }
  return null;
}

function channelLuminance(channel: number): number {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(rgb: [number, number, number]): number {
  return (
    0.2126 * channelLuminance(rgb[0]) +
    0.7152 * channelLuminance(rgb[1]) +
    0.0722 * channelLuminance(rgb[2])
  );
}

/** WCAG 2.x contrast ratio for two hex colours; 1 for unparseable input. */
export function contrastRatio(a: string, b: string): number {
  const first = parseHex(a);
  const second = parseHex(b);
  if (!first || !second) return 1;
  const la = luminance(first);
  const lb = luminance(second);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

/** True when the element needs an explicit Enter/Space activation handler. */
export function needsActivation(tag: string, role: string | null | undefined): boolean {
  const name = tag.toLowerCase();
  if (NATIVE_ACTIVATORS.has(name)) return false;
  return role === "button" || name === "tr";
}

function injectStyle(doc: Document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  (doc.head ?? doc.documentElement)?.append(style);
}

function mainLandmark(doc: Document): HTMLElement | null {
  return doc.querySelector<HTMLElement>(".app-main") ?? doc.querySelector<HTMLElement>("main");
}

function installSkipLink(doc: Document, main: HTMLElement | null): void {
  const host = doc.querySelector<HTMLElement>(".app") ?? doc.body;
  if (!host) return;

  let link = host.querySelector<HTMLAnchorElement>(`.${SKIP_CLASS}`);
  if (!link) {
    link = doc.createElement("a");
    link.className = SKIP_CLASS;
    link.href = "#wf-main";
    link.textContent = "Skip to main content";
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const target = doc.getElementById("wf-main") ?? doc.querySelector<HTMLElement>(".app-main");
      target?.focus();
    });
    link.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " " && event.key !== "Spacebar") return;
      event.preventDefault();
      const target = doc.getElementById("wf-main") ?? doc.querySelector<HTMLElement>(".app-main");
      target?.focus();
    });
  }
  if (host.firstElementChild !== link) host.prepend(link);
  if (main && !main.id) main.id = "wf-main";
  if (main && main.id === "wf-main" && !main.hasAttribute("tabindex")) {
    main.setAttribute("tabindex", "-1");
  }
}

function installHeading(doc: Document, main: HTMLElement | null): void {
  if (!main) return;
  const injected = main.querySelector<HTMLElement>(`h1.${SR_ONLY}`);
  const real = main.querySelector<HTMLElement>(`h1:not(.${SR_ONLY})`);
  if (real) {
    injected?.remove();
    return;
  }
  if (injected) return;
  const heading = doc.createElement("h1");
  heading.className = SR_ONLY;
  heading.textContent = "FinScrape market intelligence";
  main.prepend(heading);
}

function nameLandmarks(doc: Document): void {
  const header = doc.querySelector<HTMLElement>(".app-head");
  if (header) {
    if (!header.getAttribute("role")) header.setAttribute("role", "banner");
    if (!header.getAttribute("aria-label")) header.setAttribute("aria-label", "FinScrape");
  }

  const main = mainLandmark(doc);
  if (main && !main.getAttribute("aria-label")) {
    main.setAttribute("aria-label", "Market dashboard");
  }

  const rail = doc.querySelector<HTMLElement>(".app-rail");
  if (rail) {
    if (!rail.getAttribute("role")) rail.setAttribute("role", "complementary");
    if (!rail.getAttribute("aria-label")) rail.setAttribute("aria-label", "Inspector");
  }
}

function announceRegions(doc: Document): void {
  const banner = doc.querySelector<HTMLElement>(".banner-slot");
  if (banner) banner.setAttribute("aria-live", "polite");

  const feed = doc.querySelector<HTMLElement>('.panel[data-id="feed"] .panel-body');
  if (feed) {
    feed.setAttribute("aria-live", "polite");
    feed.setAttribute("aria-relevant", "additions text");
    feed.setAttribute("aria-atomic", "false");
  }
}

/** Apply every static improvement; safe to call any number of times. */
export function applyChrome(doc: Document): void {
  injectStyle(doc);
  const main = mainLandmark(doc);
  installSkipLink(doc, main);
  installHeading(doc, main);
  nameLandmarks(doc);
  announceRegions(doc);
}

function activationCandidate(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Element)) return null;
  return target.closest<HTMLElement>('tr[tabindex="0"], [role="button"]');
}

function onKeydown(doc: Document, event: KeyboardEvent): void {
  if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
    const candidate = activationCandidate(event.target);
    if (!candidate) return;
    if (!needsActivation(candidate.tagName, candidate.getAttribute("role"))) return;
    event.preventDefault();
    candidate.click();
    return;
  }

  if (event.key !== "Escape") return;
  const active = doc.activeElement;
  if (!(active instanceof Element)) return;
  if (!active.closest(".palette, .panel")) return;
  if (typeof (active as HTMLElement).blur === "function") {
    (active as HTMLElement).blur();
  }
  const main = doc.getElementById("wf-main") ?? mainLandmark(doc);
  main?.focus();
}

/**
 * Install the chrome and keyboard behaviour once per document. Returns a
 * cleanup that removes the listeners and the observer; DOM output stays.
 */
export function installA11y(doc: Document = document): () => void {
  applyChrome(doc);
  if (installedDocs.has(doc)) return () => {};

  const listener = (event: Event) => onKeydown(doc, event as KeyboardEvent);
  doc.addEventListener("keydown", listener, true);

  let observer: MutationObserver | null = null;
  if (typeof MutationObserver !== "undefined") {
    observer = new MutationObserver(() => {
      try {
        applyChrome(doc);
      } catch {
        // A shell mid-render must never break the page; the next mutation retries.
      }
    });
    observer.observe(doc.documentElement, { childList: true, subtree: true });
  }

  installedDocs.add(doc);

  return () => {
    doc.removeEventListener("keydown", listener, true);
    observer?.disconnect();
    installedDocs.delete(doc);
  };
}

if (typeof document !== "undefined" && import.meta.env.MODE !== "test") {
  installA11y(document);
}
