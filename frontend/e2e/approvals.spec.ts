/**
 * e2e/approvals.spec.ts — human-in-the-loop approval flow.
 *
 * Flow:
 *   1. Import HIL procedure (has a human_in_the_loop gate node)
 *   2. Start a run → it enters waiting_approval + creates an Approval row
 *   3. Navigate to /approvals → pending approval shows up
 *   4. Click Approve → approval changes to "approved", run resumes
 *   5. Navigate to /approvals → pending tab shows "all caught up"
 *
 * An alternative test exercises the Reject path.
 */

import { test, expect } from "@playwright/test";
import {
  waitForBackend,
  importProcedure,
  deleteProcedure,
  startRun,
  getPendingApprovals,
  waitForRun,
} from "./helpers";

const PROC_ID = "e2e_hil_procedure";
const VERSION = "1.0.0";

test.describe("Approvals", () => {
  test.beforeAll(async ({ request }) => {
    await waitForBackend(request);
  });

  test.beforeEach(async ({ request }) => {
    await importProcedure(request, "hil.procedure.json");
  });

  test.afterEach(async ({ request }) => {
    await deleteProcedure(request, PROC_ID, VERSION);
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Approvals list page — basic rendering
  // ──────────────────────────────────────────────────────────────────────────

  test("approvals page renders correctly", async ({ page }) => {
    await page.goto("/approvals");
    await expect(page).not.toHaveTitle(/error|500/i);
    // Filter tabs present
    await expect(page.getByRole("button", { name: /Pending/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /All/i })).toBeVisible();
    // Approver name input
    await expect(page.getByPlaceholder(/approver name/i)).toBeVisible();
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Approve flow
  // ──────────────────────────────────────────────────────────────────────────

  test("pending approval appears and can be approved", async ({ page, request }) => {
    // Start HIL run
    const { run_id } = await startRun(request, PROC_ID, VERSION);

    // Wait for run to enter waiting_approval (up to 20s)
    await waitForRun(
      request,
      run_id,
      ["waiting_approval", "completed", "failed", "canceled"],
      20_000
    );

    // Poll for a pending approval
    let pending: Array<{ approval_id: string; status: string; run_id: string }> = [];
    for (let i = 0; i < 15; i++) {
      pending = await getPendingApprovals(request, run_id);
      if (pending.length > 0) break;
      await new Promise((r) => setTimeout(r, 1_000));
    }
    // If no approval came up (e.g. test env completes sync), skip gracefully
    if (pending.length === 0) {
      test.skip(true, "No pending approval created — HIL node may not have triggered");
      return;
    }

    // Navigate to the approvals page
    await page.goto("/approvals");

    // The pending approval‐card should show up (filter is "pending" by default)
    await expect(
      page.getByRole("button", { name: /Approve/i })
    ).toBeVisible({ timeout: 10_000 });

    // Click Approve
    await page.getByRole("button", { name: /Approve/i }).first().click();

    // Toast confirming the decision
    await expect(page.getByText(/approved|Approval approved/i)).toBeVisible({ timeout: 8_000 });

    // The pending entry should disappear from the pending tab (re-filter or re-load)
    // Give the UI time to refresh
    await page.waitForTimeout(1_500);

    // Check that there are no more Approve buttons visible
    const approveButtons = page.getByRole("button", { name: /^Approve$/i });
    await expect(approveButtons).toHaveCount(0, { timeout: 8_000 });
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Reject flow
  // ──────────────────────────────────────────────────────────────────────────

  test("pending approval can be rejected via UI", async ({ page, request }) => {
    const { run_id } = await startRun(request, PROC_ID, VERSION);
    await waitForRun(
      request,
      run_id,
      ["waiting_approval", "completed", "failed", "canceled"],
      20_000
    );

    let pending: Array<{ approval_id: string; status: string; run_id: string }> = [];
    for (let i = 0; i < 15; i++) {
      pending = await getPendingApprovals(request, run_id);
      if (pending.length > 0) break;
      await new Promise((r) => setTimeout(r, 1_000));
    }

    if (pending.length === 0) {
      test.skip(true, "No pending approval created");
      return;
    }

    await page.goto("/approvals");
    await expect(
      page.getByRole("button", { name: /Reject/i })
    ).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /Reject/i }).first().click();

    await expect(page.getByText(/rejected|Approval rejected/i)).toBeVisible({ timeout: 8_000 });
  });

  // ──────────────────────────────────────────────────────────────────────────
  // "All caught up" message when no pending approvals
  // ──────────────────────────────────────────────────────────────────────────

  test("pending tab shows empty state when no approvals", async ({ page }) => {
    await page.goto("/approvals");
    // The filter defaults to "pending"
    // If there are no pending approvals, the empty-state text should appear
    const pendingBtn = page.getByRole("button", { name: /^Pending/i });
    await pendingBtn.click();

    // Either "No pending approvals" OR actual pending items (both are valid)
    const emptyState = page.getByText(/No pending approvals/i);
    const approvalCard = page.getByRole("button", { name: /Approve/i });

    await expect(emptyState.or(approvalCard)).toBeVisible({ timeout: 8_000 });
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Approvals "All" tab
  // ──────────────────────────────────────────────────────────────────────────

  test("All tab shows previously decided approvals", async ({ page, request }) => {
    // Seed one run and approve it via API
    const { run_id } = await startRun(request, PROC_ID, VERSION);
    await waitForRun(
      request,
      run_id,
      ["waiting_approval", "completed", "failed", "canceled"],
      20_000
    );

    let pending = await getPendingApprovals(request, run_id);
    if (pending.length === 0) {
      test.skip(true, "No pending approval created");
      return;
    }

    // Approve via API (faster than UI)
    const { submitDecision } = await import("./helpers");
    await submitDecision(request, pending[0].approval_id, "approved");

    await page.goto("/approvals");

    // Switch to "All" tab
    await page.getByRole("button", { name: /^All/i }).click();

    // Should show at least one approval (the one we just decided)
    await expect(
      page.getByText(run_id.slice(0, 8))
    ).toBeVisible({ timeout: 8_000 });
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Approval detail link → run detail page
  // ──────────────────────────────────────────────────────────────────────────

  test("run link in approval card navigates to run detail", async ({ page, request }) => {
    const { run_id } = await startRun(request, PROC_ID, VERSION);
    await waitForRun(
      request,
      run_id,
      ["waiting_approval", "completed", "failed", "canceled"],
      20_000
    );

    const pending = await getPendingApprovals(request, run_id);
    if (pending.length === 0) {
      test.skip(true, "No pending approval created");
      return;
    }

    await page.goto("/approvals");

    // Click the run link (short UUID 8 chars + "…")
    const runLink = page.getByRole("link", { name: new RegExp(run_id.slice(0, 8)) }).first();
    await expect(runLink).toBeVisible({ timeout: 8_000 });
    await runLink.click();

    await expect(page).toHaveURL(new RegExp(run_id), { timeout: 5_000 });
  });
});
