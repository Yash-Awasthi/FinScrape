import { expect, test } from "@playwright/test";

import { mockBackend } from "./mocks";

test.beforeEach(async ({ page }) => {
  await mockBackend(page);
  await page.goto("/app/");
});

test("every registered panel belongs to a view", async ({ browser }) => {
  // The layout warns when a panel is registered but in no view, or when a view names
  // a panel that does not exist. Both are invisible in the UI itself: the panel is
  // simply display:none, or the slot renders nothing.
  const context = await browser.newContext();
  const fresh = await context.newPage();
  const warnings: string[] = [];
  fresh.on("console", (msg) => {
    if (msg.type() === "warning" && msg.text().includes("[layout]")) warnings.push(msg.text());
  });
  await mockBackend(fresh);
  await fresh.goto("/app/");
  await expect(fresh.locator(".panel-head", { hasText: "Signal Feed" })).toBeVisible();
  expect(warnings).toEqual([]);
  await context.close();
});

test("dashboard shell + globe panel render", async ({ page }) => {
  // Shell mounted with the expected panels.
  await expect(page.locator(".panel-head", { hasText: "Signal Feed" })).toBeVisible();
  await expect(page.locator(".panel-head", { hasText: "Globe" })).toBeVisible();
  // globe.gl lazy-loads three.js and mounts a WebGL canvas (SwiftShader in headless).
  await expect(page.locator("section.panel canvas").first()).toBeVisible({ timeout: 20_000 });
});

test("event → ticker flow: feed row fills the inspector rail", async ({ page }) => {
  const feed = page.locator("table.feed");
  await expect(feed).toBeVisible();
  // Row carries its tickers in the table.
  const row = feed.locator("tr", { hasText: "Chip export controls" });
  await expect(row).toContainText("AAPL");
  // Click the meta line, not the headline: the headline is a link and would open
  // the source article in a new tab as well as selecting.
  await row.locator(".row-meta").click();
  // The rail is persistent — it fills in place, nothing opens over the feed.
  const inspector = page.locator(".inspector-body");
  await expect(inspector).toContainText("AAPL");
  await expect(inspector).toContainText("Apple");
  await expect(feed).toBeVisible(); // feed stays readable beside it
  await expect(row).toHaveClass(/active/);
});

test("j/k walks the feed and Esc clears the selection", async ({ page }) => {
  const rows = page.locator("table.feed tbody tr");
  // Settle the mocked WS push first: a new event prepends a row and would shift
  // every index under the assertions below.
  await expect(rows).toHaveCount(3);
  await page.keyboard.press("j");
  await expect(rows.nth(0)).toHaveClass(/active/);
  await page.keyboard.press("j");
  await expect(rows.nth(1)).toHaveClass(/active/);
  await page.keyboard.press("k");
  await expect(rows.nth(0)).toHaveClass(/active/);
  await page.keyboard.press("Escape");
  await expect(page.locator("table.feed tbody tr.active")).toHaveCount(0);
  await expect(page.locator(".inspector-body")).toContainText("Select a signal");
});

test("WS update: new_events frame appends a row live", async ({ page }) => {
  const rows = page.locator("table.feed tbody tr");
  await expect(rows).toHaveCount(2); // INIT_EVENTS
  // The mocked socket pushes a third event ~1.2s in.
  await expect(rows).toHaveCount(3);
  await expect(page.locator("table.feed")).toContainText("central bank surprise hike");
});

test("tabs switch views and the URL hash follows", async ({ page }) => {
  await page.getByRole("link", { name: "Track record" }).click();
  await expect(page).toHaveURL(/#record$/);
  await expect(page.locator(".panel-head", { hasText: "Scored calls" })).toBeVisible();
  await expect(page.locator(".panel-head", { hasText: "Signal Feed" })).toBeHidden();
  // No event is picked on this view, so the inspector rail gives up its width.
  await expect(page.locator(".inspector")).toBeHidden();
  await page.getByRole("link", { name: "Today" }).click();
  await expect(page.locator(".panel-head", { hasText: "Signal Feed" })).toBeVisible();
});

test("a deep link opens its view", async ({ page }) => {
  await page.goto("/app/#sources");
  await expect(page.locator(".panel-head", { hasText: "Source health" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sources" })).toHaveAttribute("aria-current", "page");
});

test("charting a ticker opens Tickers with the calls that named it", async ({ page }) => {
  await expect(page.locator("table.feed")).toContainText("Chip export controls");
  await page.evaluate(() =>
    window.dispatchEvent(new CustomEvent("worldfin:select-symbol", { detail: "AAPL" })),
  );
  await expect(page).toHaveURL(/#tickers$/);
  await expect(page.locator(".candles-calls")).toContainText("Chip export controls");
});
