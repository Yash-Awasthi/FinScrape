import { expect, test } from "@playwright/test";

import { mockBackend } from "./mocks";

// Paid-for web behaviour that the typechecker cannot see (plan M3.3):
//
//  1. the globe's 1.8MB chunk is requested only by the view that shows it;
//  2. the shell's largest paint is inside the 2.5 s mid-range budget;
//  3. a reduced-motion visitor gets the globe without the drift.
//
// These run on the built app, not the dev server, so the numbers are the shipped ones.
// A developer laptop is faster than a mid-range phone; the LCP bound is deliberately
// loose enough to be a regression alarm rather than a device certification.

test("the globe chunk is not fetched by a view that does not show it", async ({ page }) => {
  const chunks: string[] = [];
  page.on("request", (req) => {
    if (/globe\.gl[-.]/.test(req.url())) chunks.push(req.url());
  });
  await mockBackend(page);
  await page.goto("/app/#tickers");
  await expect(page.locator(".panel-head", { hasText: "Market" })).toBeVisible();
  // Give the deferred import every chance to fire: it is scheduled from showView, so
  // if a non-Today entry point ever requested it, it would have by now.
  await page.waitForTimeout(1500);
  expect(chunks).toEqual([]);
});

test("the globe chunk arrives once Today is shown", async ({ page }) => {
  const chunks: string[] = [];
  page.on("request", (req) => {
    if (/globe\.gl[-.]/.test(req.url())) chunks.push(req.url());
  });
  await mockBackend(page);
  await page.goto("/app/");
  await expect(page.locator("section.panel canvas").first()).toBeVisible({ timeout: 20_000 });
  expect(chunks.length).toBe(1);
});

test("LCP is inside the 2.5 s mid-range budget", async ({ page }) => {
  await mockBackend(page);
  await page.addInitScript(() => {
    const observer = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      const last = entries[entries.length - 1];
      if (last) (window as unknown as { __lcp?: number }).__lcp = last.startTime;
    });
    observer.observe({ type: "largest-contentful-paint", buffered: true });
  });
  await page.goto("/app/");
  await expect(page.locator(".panel-head", { hasText: "Signal Feed" })).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __lcp?: number }).__lcp ?? 0))
    .toBeGreaterThan(0);
  const lcp = await page.evaluate(() => (window as unknown as { __lcp?: number }).__lcp ?? 0);
  expect(lcp).toBeLessThan(2500);
});

test("reduced motion stops the globe's auto-rotation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockBackend(page);
  await page.goto("/app/");
  await expect(page.locator("section.panel canvas").first()).toBeVisible({ timeout: 20_000 });
  // globe.gl exposes its controls on `__threeObj` in dev; in the shipped bundle we
  // assert the observable: two screenshots a second apart are identical when the
  // globe is still, and differ when it drifts.
  const globePanel = page.locator("section.panel", { hasText: "Globe" });
  const first = await globePanel.screenshot();
  await page.waitForTimeout(1000);
  const second = await globePanel.screenshot();
  expect(Buffer.compare(first, second)).toBe(0);
});
