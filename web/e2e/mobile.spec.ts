import { expect, test } from "@playwright/test";

import { mockBackend } from "./mocks";

const VIEWPORT = { width: 390, height: 844 };
const ALLOWED_SCROLL_WIDTH = VIEWPORT.width + 1;

test.beforeEach(async ({ page }) => {
  await mockBackend(page);
  await page.setViewportSize(VIEWPORT);
  await page.goto("/app/");
});

test("bottom nav lists every view and reaches the thumb", async ({ page }) => {
  const tabs = page.locator('nav.tabs[aria-label="views"]');
  await expect(tabs).toBeVisible();
  const box = await tabs.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  expect(box.y).toBeGreaterThanOrEqual(VIEWPORT.height - 120);
  expect(box.y + box.height).toBeLessThanOrEqual(VIEWPORT.height);

  const links = tabs.locator("a");
  await expect(links).toHaveCount(5);
  for (let i = 0; i < 5; i += 1) {
    const linkBox = await links.nth(i).boundingBox();
    expect(linkBox).not.toBeNull();
    if (!linkBox) continue;
    expect(linkBox.height).toBeGreaterThanOrEqual(44);
  }
});

test("no horizontal scroll on any view", async ({ page }) => {
  const scrollWidth = () => page.evaluate(() => document.documentElement.scrollWidth);
  expect(await scrollWidth()).toBeLessThanOrEqual(ALLOWED_SCROLL_WIDTH);

  // Track record and Sources carry the wide .grid-table.
  const labels = ["Today", "My Desk", "Tickers", "Track record", "Sources"];
  for (const label of labels) {
    const link = page.getByRole("link", { name: label, exact: true });
    await link.click();
    await expect(link).toHaveAttribute("aria-current", "page");
    expect(await scrollWidth()).toBeLessThanOrEqual(ALLOWED_SCROLL_WIDTH);
  }
});

test("refresh floats within thumb reach", async ({ page }) => {
  const refresh = page.getByRole("button", { name: "Refresh feed and panels" });
  await expect(refresh).toBeVisible();
  const box = await refresh.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(box.y).toBeGreaterThan(600);
});
