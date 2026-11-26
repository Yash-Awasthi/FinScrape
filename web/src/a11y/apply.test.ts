import { readFileSync } from "node:fs";

import { beforeEach, expect, it } from "vite-plus/test";

import { INIT_EVENTS } from "../../e2e/mocks";
import { Shell } from "../app/shell";
import { parseRoute } from "../app/routes";
import { renderEventPage, type EventPageData } from "../pages/event";
import { applyChrome, contrastRatio, installA11y, needsActivation } from "./apply";

function shell(): void {
  document.body.innerHTML = `
    <div class="app">
      <header class="app-head">
        <div class="brand">FinScrape</div>
        <nav class="tabs" aria-label="views">
          <a href="#feed" data-view="feed">Feed</a>
        </nav>
      </header>
      <div class="banner-slot"></div>
      <main class="app-main">
        <div class="panel" data-id="feed">
          <div class="panel-body">
            <table><tbody>
              <tr tabindex="0" data-event-id="1"><td>row one</td></tr>
            </tbody></table>
          </div>
        </div>
      </main>
      <aside class="app-rail"></aside>
      <div class="palette"><input aria-label="Search" /></div>
    </div>
  `;
}

beforeEach(() => {
  shell();
});

it("puts the skip link first and applies the chrome only once", () => {
  installA11y(document);
  installA11y(document);
  applyChrome(document);

  const app = document.querySelector(".app")!;
  const link = app.firstElementChild as HTMLAnchorElement;
  expect(link.classList.contains("wf-skip")).toBe(true);
  expect(link.textContent).toBe("Skip to main content");
  expect(document.querySelectorAll(".wf-skip")).toHaveLength(1);
  expect(document.querySelectorAll("style#wf-a11y-style")).toHaveLength(1);
  expect(document.querySelectorAll("h1.wf-sr-only")).toHaveLength(1);
});

it("names the landmarks", () => {
  applyChrome(document);
  expect(document.querySelector(".app-head")!.getAttribute("role")).toBe("banner");
  expect(document.querySelector(".app-head")!.getAttribute("aria-label")).toBe("FinScrape");
  expect(document.querySelector("nav.tabs")!.getAttribute("aria-label")).toBe("views");
  expect(document.querySelector("main")!.getAttribute("aria-label")).toBe("Market dashboard");
  expect(document.querySelector(".app-rail")!.getAttribute("role")).toBe("complementary");
  expect(document.querySelector(".app-rail")!.getAttribute("aria-label")).toBe("Inspector");
  expect(document.querySelector(".app-main")!.id).toBe("wf-main");
  expect(document.querySelector(".app-main")!.getAttribute("tabindex")).toBe("-1");
});

it("sets the two polite live regions", () => {
  applyChrome(document);
  expect(document.querySelector(".banner-slot")!.getAttribute("aria-live")).toBe("polite");
  const feed = document.querySelector('.panel[data-id="feed"] .panel-body')!;
  expect(feed.getAttribute("aria-live")).toBe("polite");
  expect(feed.getAttribute("aria-relevant")).toBe("additions text");
  expect(feed.getAttribute("aria-atomic")).toBe("false");
});

it("activates a focused table row with Enter exactly once", () => {
  installA11y(document);
  installA11y(document);
  const row = document.querySelector<HTMLTableRowElement>('tr[data-event-id="1"]')!;
  let clicks = 0;
  row.addEventListener("click", () => {
    clicks += 1;
  });
  row.focus();
  const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
  row.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  expect(clicks).toBe(1);
});

it("moves focus to the main landmark when Escape leaves the palette", () => {
  installA11y(document);
  const input = document.querySelector<HTMLInputElement>(".palette input")!;
  input.focus();
  input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  expect(document.activeElement).toBe(document.querySelector("#wf-main"));
});

it("moves focus to the main landmark when Escape leaves a panel", () => {
  installA11y(document);
  const body = document.querySelector<HTMLElement>('.panel[data-id="feed"] .panel-body')!;
  const input = document.createElement("input");
  body.append(input);
  input.focus();
  input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  expect(document.activeElement).toBe(document.querySelector("#wf-main"));
});

it("marks exactly one active tab and moves aria-current with the view", () => {
  const nav = document.querySelector<HTMLElement>("nav.tabs")!;
  nav.innerHTML = `
    <a href="#feed" data-view="feed">Feed</a>
    <a href="#desk" data-view="desk">Desk</a>
  `;
  const content = document.querySelector<HTMLElement>(".app-main")!;
  const shell = { content, tabs: nav } as unknown as Shell;

  Shell.prototype.setView.call(shell, "feed");
  expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  expect(nav.querySelector('[data-view="feed"]')!.getAttribute("aria-current")).toBe("page");
  expect(nav.querySelector('[data-view="desk"]')!.hasAttribute("aria-current")).toBe(false);

  Shell.prototype.setView.call(shell, "desk");
  expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  expect(nav.querySelector('[data-view="desk"]')!.getAttribute("aria-current")).toBe("page");
  expect(nav.querySelector('[data-view="feed"]')!.hasAttribute("aria-current")).toBe(false);
});

it("activates a role=button with Space exactly once", () => {
  installA11y(document);
  const button = document.createElement("div");
  button.setAttribute("role", "button");
  button.tabIndex = 0;
  button.textContent = "run";
  document.querySelector(".app")!.append(button);
  let clicks = 0;
  button.addEventListener("click", () => {
    clicks += 1;
  });
  button.focus();
  const event = new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true });
  button.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  expect(clicks).toBe(1);
});

it("computes WCAG contrast for the changed tokens", () => {
  expect(contrastRatio("#f25b64", "#121621")).toBeCloseTo(5.55, 1);
  expect(contrastRatio("#ffffff", "#2563eb")).toBeCloseTo(5.17, 1);
  expect(contrastRatio("#4b8ef7", "#1b2740")).toBeGreaterThanOrEqual(4.6);
});

it("knows which elements need explicit keyboard activation", () => {
  expect(needsActivation("button", null)).toBe(false);
  expect(needsActivation("a", null)).toBe(false);
  expect(needsActivation("input", null)).toBe(false);
  expect(needsActivation("div", "button")).toBe(true);
  expect(needsActivation("tr", null)).toBe(true);
  expect(needsActivation("div", null)).toBe(false);
});

it("renders the event page with exactly one h1", () => {
  const page = renderEventPage(INIT_EVENTS[0] as unknown as EventPageData);
  expect(page.querySelectorAll("h1")).toHaveLength(1);
  expect(parseRoute("/app/event/1")).toEqual({ kind: "event", id: 1 });
  expect(parseRoute("/app/")).toBeNull();
});

it("keeps a visible focus ring in the dashboard stylesheet", () => {
  const css = readFileSync("src/styles.css", "utf8");
  const rule = /:focus-visible\s*\{([^}]*)\}/.exec(css);
  expect(rule).not.toBeNull();
  const body = rule![1];
  if (/outline\s*:\s*none/.test(body)) {
    expect(/box-shadow\s*:/.test(body) || /outline\s*:\s*(?!none)/.test(body)).toBe(true);
  }
});
