import { expect, it } from "vite-plus/test";

import { citeLink, claimWithCite, eventHref, safeArticle, scenarioHref } from "./citation";

function anchor(html: string): HTMLAnchorElement {
  const host = document.createElement("div");
  host.innerHTML = html;
  const a = host.querySelector<HTMLAnchorElement>("a.cite");
  if (!a) throw new Error("no cite anchor rendered");
  return a;
}

it("links the first article when it is a real web URL", () => {
  const a = anchor(
    citeLink({ id: 7, sources: ["gdelt/reuters.com:wire"], articles: ["https://example.test/a"] }),
  );
  expect(a.getAttribute("href")).toBe("https://example.test/a");
  expect(safeArticle("https://example.test/a")).toBe("https://example.test/a");
  expect(a.target).toBe("_blank");
  expect(a.rel).toContain("noopener");
});

it("falls back to the event evidence page without an article", () => {
  const none = anchor(citeLink({ id: 7, sources: ["world/bbc_world:mainstream"], articles: [] }));
  expect(none.getAttribute("href")).toBe("/app/event/7");
  expect(none.getAttribute("href")).toBe(eventHref(7));
  expect(none.title).toContain("open the event evidence page");
  expect(none.target).toBe("");

  const missing = anchor(citeLink({ id: 7, sources: ["world/bbc_world:mainstream"] }));
  expect(missing.getAttribute("href")).toBe("/app/event/7");
});

it("rejects a script URL and falls back to the event page", () => {
  expect(safeArticle("javascript:alert(1)")).toBeNull();
  expect(safeArticle(undefined)).toBeNull();
  const a = anchor(
    citeLink({
      id: 7,
      sources: ["world/bbc_world:mainstream"],
      articles: ["javascript:alert(1)"],
    }),
  );
  expect(a.getAttribute("href")).toBe("/app/event/7");
});

it("names the source with sourceLabel and never injects its markup", () => {
  const a = anchor(
    citeLink({ id: 7, sources: ["gdelt/reuters<b>:wire"], articles: ["https://example.test/a"] }),
  );
  expect(a.textContent).toContain("source: reuters<b>");
  expect(a.textContent).toContain("1 article");
  expect(a.querySelector("b")).toBeNull();
  expect(a.children.length).toBe(0);
});

it("says the source is unrecorded but still links the claim", () => {
  const a = anchor(citeLink({ id: 7 }, "why this call"));
  expect(a.getAttribute("href")).toBe("/app/event/7");
  expect(a.textContent).toContain("not recorded");
  expect(a.title).toContain("source not recorded");
  expect(a.title).toContain("why this call");
});

it("claimWithCite escapes the claim and appends exactly one citation", () => {
  const host = document.createElement("div");
  host.innerHTML = claimWithCite('<img src=x onerror="alert(1)">', {
    id: 7,
    sources: ["world/bbc_world:mainstream"],
    articles: ["https://example.test/a"],
  });
  expect(host.querySelector("img")).toBeNull();
  expect(host.textContent).toContain('<img src=x onerror="alert(1)">');
  expect(host.querySelectorAll("a.cite").length).toBe(1);
});

it("encodes a scenario id for its evidence page", () => {
  expect(scenarioHref("s1")).toBe("/app/scenario/s1");
  expect(scenarioHref("leg up/1")).toBe("/app/scenario/leg%20up%2F1");
});
