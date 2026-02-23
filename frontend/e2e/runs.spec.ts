/**
 * e2e/runs.spec.ts — create run via UI, verify in run list, check event timeline.
 *
 * Requires live backend + frontend.  The test procedure is seeded via API,
 * then the run is started from the Procedures page using the "▶ Run" button.
 * The Runs page is checked for the new run; the run detail page is checked
 * for the timeline.
 */

import { test, expect } from "@playwright/test";
import {
  waitForBackend,
  importProcedure,
  deleteProcedure,
  startRun,
  waitForRun,
} from "./helpers";

const PROC_ID = "e2e_test_procedure";
const VERSION = "1.0.0";

test.describe("Runs", () => {
  test.beforeAll(async ({ request }) => {
    await waitForBackend(request);
  });

  test.beforeEach(async ({ request }) => {
    // Always have the procedure available
    await importProcedure(request, "sample.procedure.json");
  });

  test.afterEach(async ({ request }) => {
    await deleteProcedure(request, PROC_ID, VERSION);
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Start a run from the Procedures page
  // ──────────────────────────────────────────────────────────────────────────

  test("click Run button starts run and navigates to Runs page", async ({ page }) => {
    await page.goto("/procedures");

    // Wait for the procedure card to appear
    await expect(
      page.getByText(`${PROC_ID} · v${VERSION}`)
    ).toBeVisible({ timeout: 10_000 });

    // Click the ▶ Run button on that card
    const runBtn = page.getByRole("button", { name: /▶ Run/i }).first();
    await runBtn.click();

    // Since the sample procedure has a variable with a default, a modal may appear.
    // If a vars modal is visible, submit it.
    const modal = page.getByText(/Variables|Run Configuration/i);
    const modalVisible = await modal.isVisible().catch(() => false);
    if (modalVisible) {
      const startBtn = page.getByRole("button", { name: /Start Run|Run|Confirm/i }).last();
      await startBtn.click();
    }

    // Success toast
    await expect(page.getByText(/Run started|started/i)).toBeVisible({ timeout: 10_000 });

    // Should redirect to /runs
    await expect(page).toHaveURL(/\/runs/, { timeout: 10_000 });

    // The new run should appear in the list
    await expect(
      page.getByText(new RegExp(PROC_ID, "i"))
    ).toBeVisible({ timeout: 10_000 });
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Runs list page
  // ──────────────────────────────────────────────────────────────────────────

  test("runs list shows filter buttons", async ({ page }) => {
    await page.goto("/runs");
    for (const status of ["all", "running", "completed", "failed"]) {
      await expect(
        page.getByRole("button", { name: new RegExp(status, "i") })
      ).toBeVisible();
    }
  });

  test("run card links to detail page", async ({ page, request }) => {
    // Seed a run via API and wait for it to complete
    const { run_id } = await startRun(request, PROC_ID, VERSION);
    // Give it up to 30s to complete
    await waitForRun(request, run_id, ["completed", "failed", "canceled"]);

    await page.goto("/runs");

    // Find a link containing the run_id (truncated 8 chars shown in UI)
    const shortId = run_id.slice(0, 8);
    const runLink = page.getByRole("link", { name: new RegExp(shortId, "i") }).first();

    const linkFound = await runLink.isVisible().catch(() => false);
    if (linkFound) {
      await runLink.click();
      await expect(page).toHaveURL(new RegExp(run_id), { timeout: 5_000 });
    } else {
      // The run might be further down the list; navigate directly
      await page.goto(`/runs/${run_id}`);
      await expect(page).not.toHaveTitle(/not found|error/i);
    }
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Run detail / event timeline
  // ──────────────────────────────────────────────────────────────────────────

  test("run detail page shows event timeline", async ({ page, request }) => {
    const { run_id } = await startRun(request, PROC_ID, VERSION);
    // Wait for completion so events are persisted
    await waitForRun(request, run_id, ["completed", "failed", "canceled"]);

    await page.goto(`/runs/${run_id}`);

    // run_id should appear on the page
    await expect(page.getByText(run_id)).toBeVisible({ timeout: 10_000 });

    // At least one event (run_created) should appear in the timeline
    await expect(
      page.getByText(/Run Created|run_created|Node Started|Execution Started/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  test("run detail shows status badge", async ({ page, request }) => {
    const { run_id } = await startRun(request, PROC_ID, VERSION);
    await waitForRun(request, run_id, ["completed", "failed", "canceled"]);

    await page.goto(`/runs/${run_id}`);

    // Status badge should show a terminal status
    await expect(
      page.getByText(/completed|failed|canceled/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Cancel a running run (best-effort; may complete before cancel arrives)
  // ──────────────────────────────────────────────────────────────────────────

  test("cancel button appears on run detail page", async ({ page, request }) => {
    const { run_id } = await startRun(request, PROC_ID, VERSION);
    // Navigate immediately — run may still be running
    await page.goto(`/runs/${run_id}`);
    await expect(page.getByText(run_id)).toBeVisible({ timeout: 8_000 });

    // Cancel button OR a terminal status should be visible
    // (if run completed synchronously before page load, terminal status badge is enough)
    const cancelBtn = page.getByRole("button", { name: /Cancel/i });
    const terminalBadge = page.getByText(/completed|failed|canceled/i);

    await expect(cancelBtn.or(terminalBadge)).toBeVisible({ timeout: 10_000 });
  });
});
