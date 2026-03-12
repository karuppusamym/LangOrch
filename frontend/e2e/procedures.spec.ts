/**
 * e2e/procedures.spec.ts — import procedure via UI + verify it appears in the list.
 *
 * Requires:
 *   - Frontend dev server on http://localhost:3000
 *   - LangOrch backend API on http://localhost:8000
 *
 * Setup:  imports a test procedure before each test via direct API call.
 * Teardown: deletes the test procedure after each test via direct API call.
 */

import { test, expect } from "@playwright/test";
import { authenticatePage, waitForBackend, importProcedure, deleteProcedure, loadFixture } from "./helpers";

const PROC_ID = "e2e_test_procedure";
const VERSION = "1.0.0";

test.describe("Procedures page", () => {
  test.beforeAll(async ({ request }) => {
    await waitForBackend(request);
  });

  test.beforeEach(async ({ page, request }) => {
    await authenticatePage(page, request);
  });

  test.afterEach(async ({ request }) => {
    await deleteProcedure(request, PROC_ID, VERSION);
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Import via UI
  // ──────────────────────────────────────────────────────────────────────────

  test("import procedure via UI shows it in the list", async ({ page }) => {
    const ckpJson = loadFixture("sample.procedure.json");

    await page.goto("/procedures");
    // Click "Import CKP" button
    await page.getByRole("button", { name: /Import CKP/i }).click();

    await expect(page.getByRole("heading", { name: /Import CKP Procedure/i })).toBeVisible();

    // Fill the textarea with the fixture JSON
    const textarea = page.locator("textarea").first();
    await textarea.fill(JSON.stringify(ckpJson));

    // Click "Import" inside the dialog
    await page.getByRole("button", { name: /^Import$/i }).click();

    // Success toast should appear
    await expect(page.getByText(/imported successfully/i)).toBeVisible({ timeout: 8_000 });

    const row = page.getByRole("row").filter({ has: page.getByText(PROC_ID, { exact: true }) });
    await expect(row).toBeVisible({ timeout: 8_000 });
    await expect(row.getByText(`v${VERSION}`, { exact: true })).toBeVisible();
  });

  test("import with invalid JSON shows error", async ({ page }) => {
    await page.goto("/procedures");
    await page.getByRole("button", { name: /Import CKP/i }).click();
    await expect(page.getByRole("heading", { name: /Import CKP Procedure/i })).toBeVisible();

    const textarea = page.locator("textarea").first();
    await textarea.fill('{ invalid json }');
    await page.getByRole("button", { name: /^Import$/i }).click();

    // Error message should appear in dialog
    await expect(page.getByText(/Import failed:/i)).toBeVisible({ timeout: 5_000 });

    // Dialog should still be open
    await expect(page.getByRole("heading", { name: /Import CKP Procedure/i })).toBeVisible();

    // Close it
    await page.getByRole("button", { name: /Cancel/i }).click();
    await expect(page.getByRole("heading", { name: /Import CKP Procedure/i })).not.toBeVisible();
  });

  // ──────────────────────────────────────────────────────────────────────────
  // List via API-seeded data
  // ──────────────────────────────────────────────────────────────────────────

  test("imported procedure appears in list with correct fields", async ({
    page,
    request,
  }) => {
    // Seed via API for speed
    await importProcedure(request, "sample.procedure.json");

    await page.goto("/procedures");

    const row = page.getByRole("row").filter({ has: page.getByText(PROC_ID, { exact: true }) });
    await expect(row).toBeVisible({ timeout: 8_000 });
    await expect(row.getByText(`v${VERSION}`, { exact: true })).toBeVisible();

    // Should have a Run button
    const runBtn = row.getByRole("button", { name: /^Run$/i });
    await expect(runBtn).toBeVisible();
    await expect(runBtn).toBeEnabled();
  });

  test("search box filters procedure list", async ({ page, request }) => {
    await importProcedure(request, "sample.procedure.json");

    await page.goto("/procedures");
    const row = page.getByRole("row").filter({ has: page.getByText(PROC_ID, { exact: true }) });
    await expect(row).toBeVisible({ timeout: 8_000 });

    // Type a search term that matches
    await page.getByPlaceholder("Search procedures…").fill("e2e_test");
    await expect(row).toBeVisible();

    // Type something that doesn't match
    await page.getByPlaceholder("Search procedures…").fill("xyzzy_no_match");
    // Procedure should disappear from visible list
    await expect(row).not.toBeVisible();
  });

  test("procedure detail page loads", async ({ page, request }) => {
    await importProcedure(request, "sample.procedure.json");

    await page.goto(`/procedures/${PROC_ID}/${VERSION}`);

    // Should not be a 404 / error page
    await expect(page).not.toHaveTitle(/not found|error/i);
    await expect(page.getByRole("heading", { name: PROC_ID })).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText(`ID: ${PROC_ID} · Version: ${VERSION}`)).toBeVisible();
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Status filter
  // ──────────────────────────────────────────────────────────────────────────

  test("status filter 'active' shows only active procedures", async ({
    page,
    request,
  }) => {
    const proc = await importProcedure(request, "sample.procedure.json");

    await page.goto("/procedures");
    const row = page.getByRole("row").filter({ has: page.getByText(PROC_ID, { exact: true }) });
    await expect(row).toBeVisible({ timeout: 8_000 });

    // Filter by the status returned by the backend for this fixture.
    const statusFilter = page.getByRole("combobox", { name: /Filter by status/i });
    await statusFilter.selectOption(proc.status);

    // Should still be visible
    await expect(row).toBeVisible();

    const alternateStatus = proc.status === "draft" ? "active" : "draft";
    await statusFilter.selectOption(alternateStatus);
    await expect(row).not.toBeVisible();
  });
});
