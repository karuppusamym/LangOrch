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
import { waitForBackend, importProcedure, deleteProcedure, loadFixture } from "./helpers";
import * as fs from "fs";
import * as path from "path";

const PROC_ID = "e2e_test_procedure";
const VERSION = "1.0.0";

test.describe("Procedures page", () => {
  test.beforeAll(async ({ request }) => {
    await waitForBackend(request);
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

    // The import dialog should appear with "Paste CKP JSON" heading
    await expect(page.getByText("Paste CKP JSON")).toBeVisible();

    // Fill the textarea with the fixture JSON
    const textarea = page.locator("textarea");
    await textarea.fill(JSON.stringify(ckpJson));

    // Click "Import" inside the dialog
    await page.getByRole("button", { name: /^Import$/i }).click();

    // Success toast should appear
    await expect(page.getByText(/imported successfully/i)).toBeVisible({ timeout: 8_000 });

    // The dialog should close
    await expect(page.getByText("Paste CKP JSON")).not.toBeVisible();

    // The procedure should appear in the list
    await expect(
      page.getByText(`${PROC_ID} · v${VERSION}`)
    ).toBeVisible({ timeout: 8_000 });
  });

  test("import with invalid JSON shows error", async ({ page }) => {
    await page.goto("/procedures");
    await page.getByRole("button", { name: /Import CKP/i }).click();
    await expect(page.getByText("Paste CKP JSON")).toBeVisible();

    const textarea = page.locator("textarea");
    await textarea.fill('{ invalid json }');
    await page.getByRole("button", { name: /^Import$/i }).click();

    // Error message should appear in dialog
    await expect(page.getByText(/invalid|error|failed/i)).toBeVisible({ timeout: 5_000 });

    // Dialog should still be open
    await expect(page.getByText("Paste CKP JSON")).toBeVisible();

    // Close it
    await page.getByRole("button", { name: /Cancel/i }).click();
    await expect(page.getByText("Paste CKP JSON")).not.toBeVisible();
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

    // Procedure card should show ID + version
    await expect(
      page.getByText(`${PROC_ID} · v${VERSION}`)
    ).toBeVisible({ timeout: 8_000 });

    // Should have a Run button
    const runBtn = page.getByRole("button", { name: /▶ Run/i }).first();
    await expect(runBtn).toBeVisible();
    await expect(runBtn).toBeEnabled();
  });

  test("search box filters procedure list", async ({ page, request }) => {
    await importProcedure(request, "sample.procedure.json");

    await page.goto("/procedures");
    await expect(page.getByText(`${PROC_ID} · v${VERSION}`)).toBeVisible({ timeout: 8_000 });

    // Type a search term that matches
    await page.getByPlaceholder("Search procedures…").fill("e2e_test");
    await expect(page.getByText(`${PROC_ID} · v${VERSION}`)).toBeVisible();

    // Type something that doesn't match
    await page.getByPlaceholder("Search procedures…").fill("xyzzy_no_match");
    // Procedure should disappear from visible list
    await expect(
      page.getByText(`${PROC_ID} · v${VERSION}`)
    ).not.toBeVisible();
  });

  test("procedure detail page loads", async ({ page, request }) => {
    await importProcedure(request, "sample.procedure.json");

    await page.goto(`/procedures/${PROC_ID}/${VERSION}`);

    // Should not be a 404 / error page
    await expect(page).not.toHaveTitle(/not found|error/i);
    // Should show the procedure ID somewhere on the page
    await expect(page.getByText(PROC_ID)).toBeVisible({ timeout: 8_000 });
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Status filter
  // ──────────────────────────────────────────────────────────────────────────

  test("status filter 'active' shows only active procedures", async ({
    page,
    request,
  }) => {
    await importProcedure(request, "sample.procedure.json");

    await page.goto("/procedures");
    await expect(page.getByText(`${PROC_ID} · v${VERSION}`)).toBeVisible({ timeout: 8_000 });

    // Filter by "active" — procedure was imported as active
    const statusFilter = page.getByRole("combobox", { name: /Filter by status/i });
    await statusFilter.selectOption("active");

    // Should still be visible
    await expect(page.getByText(`${PROC_ID} · v${VERSION}`)).toBeVisible();

    // Filter by "archived" — should be gone
    await statusFilter.selectOption("archived");
    await expect(page.getByText(`${PROC_ID} · v${VERSION}`)).not.toBeVisible();
  });
});
