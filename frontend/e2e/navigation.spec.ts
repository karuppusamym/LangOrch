/**
 * e2e/navigation.spec.ts — smoke tests: every top-level page loads without errors.
 *
 * These run quickly and serve as a "did we break the build" gate.
 * They do NOT require a live backend (pages gracefully show loading/empty state).
 */

import { test, expect } from "@playwright/test";
import { authenticatePage } from "./helpers";

const PAGES = [
  { path: "/",              heading: /LangOrch|Procedures|Overview/i },
  { path: "/procedures",   heading: /Procedures/i },
  { path: "/runs",         heading: /Runs/i },
  { path: "/approvals",    heading: /Approvals/i },
  { path: "/agents",       heading: /Agents/i },
];

for (const { path, heading } of PAGES) {
  test(`page loads: ${path}`, async ({ page, request }) => {
    await authenticatePage(page, request);
    await page.goto(path);
    // Page should not show a Next.js 500 error
    await expect(page).not.toHaveTitle(/Application error|500/i);
    await expect(page.locator("aside").first()).toBeVisible();
    await expect(page.getByText(heading).first()).toBeVisible();
  });
}

test("sidebar navigation links are present", async ({ page, request }) => {
  await authenticatePage(page, request);
  await page.goto("/");
  // The sidebar should contain links to all main sections
  const nav = page.locator("aside").first();
  await expect(nav.getByRole("link", { name: /Procedures/i })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Runs/i })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Approvals/i })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Agents/i })).toBeVisible();
});

test("procedures link navigates correctly", async ({ page, request }) => {
  await authenticatePage(page, request);
  await page.goto("/");
  await page.locator("aside").first().getByRole("link", { name: /^Procedures$/i }).click();
  await expect(page).toHaveURL(/\/procedures/);
  await expect(page.getByRole("heading", { name: /Procedures/i })).toBeVisible();
});

test("runs link navigates correctly", async ({ page, request }) => {
  await authenticatePage(page, request);
  await page.goto("/");
  await page.locator("aside").first().getByRole("link", { name: /^Runs$/i }).click();
  await expect(page).toHaveURL(/\/runs/);
  await expect(page.getByRole("heading", { name: /Runs/i })).toBeVisible();
});
