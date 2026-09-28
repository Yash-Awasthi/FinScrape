import { expect, test } from "@playwright/test";

// Runs against the real API and the `server.seed` dataset; see playwright.live.config.ts.
test("seeded events flow through feed, inspector and scenarios", async ({ page }) => {
  await page.goto("/app/");

  const feed = page.locator("table.feed");
  const row = feed.locator("tr", { hasText: "Strait of Hormuz" }).first();
  await expect(row).toBeVisible();
  await expect(row).toContainText("XOM");

  await row.locator(".row-meta").click();
  const inspector = page.locator(".inspector-body");
  await expect(inspector).toContainText("Strait of Hormuz");
  await expect(inspector).toContainText("Oil majors");

  const cards = page.locator(".sc-card");
  await expect(cards.first()).toBeVisible();
  await expect(cards.first().locator(".sc-prob")).toHaveText(/\d+%/);
});
