/**
 * e2e/navigation.spec.ts — smoke tests: every top-level page loads without errors.
 *
 * These run quickly and serve as a "did we break the build" gate.
 * They do NOT require a live backend (pages gracefully show loading/empty state).
 */

import { test, expect } from "@playwright/test";

const PAGES = [
  { path: "/",              heading: /LangOrch|Procedures|Overview/i },
  { path: "/procedures",   heading: /Procedures/i },
  { path: "/runs",         heading: /Runs/i },
  { path: "/approvals",    heading: /Approvals/i },
  { path: "/agents",       heading: /Agents/i },
];

for (const { path, heading } of PAGES) {
  test(`page loads: ${path}`, async ({ page }) => {
    await page.goto(path);
    // Page should not show a Next.js 500 error
    await expect(page).not.toHaveTitle(/Application error|500/i);
    // Sidebar navigation should be visible
    await expect(page.locator("nav, aside")).toBeVisible();
  });
}

test("sidebar navigation links are present", async ({ page }) => {
  await page.goto("/");
  // The sidebar should contain links to all main sections
  const nav = page.locator("nav, aside");
  await expect(nav.getByRole("link", { name: /Procedures/i })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Runs/i })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Approvals/i })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Agents/i })).toBeVisible();
});

test("procedures link navigates correctly", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /Procedures/i }).first().click();
  await expect(page).toHaveURL(/\/procedures/);
});

test("runs link navigates correctly", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /Runs/i }).first().click();
  await expect(page).toHaveURL(/\/runs/);
});
