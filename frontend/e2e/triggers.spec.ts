import { test, expect } from "@playwright/test";
import { authenticatePage, deleteProcedure, importProcedure, waitForBackend } from "./helpers";

const PROC_ID = "e2e_test_procedure";
const VERSION = "1.0.0";

test.describe("Procedure trigger tab", () => {
  test.beforeAll(async ({ request }) => {
    await waitForBackend(request);
  });

  test.beforeEach(async ({ page, request }) => {
    await authenticatePage(page, request);
    await importProcedure(request, "sample.procedure.json");
  });

  test.afterEach(async ({ request }) => {
    await deleteProcedure(request, PROC_ID, VERSION);
  });

  test("webhook trigger requires a secret env var before save", async ({ page }) => {
    await page.goto(`/procedures/${PROC_ID}/${VERSION}?tab=trigger`);

    await expect(page.getByText(/Trigger Configuration/i)).toBeVisible();
    await expect(page.getByText(/Webhook triggers require a secret env var name/i)).toBeVisible();

    const saveButton = page.getByRole("button", { name: /Register Trigger|Update Trigger/i });
    await expect(saveButton).toBeDisabled();

    await page.getByLabel(/Webhook Secret Env Var/i).fill("MY_TRIGGER_SECRET");
    await expect(page.getByText(/Webhook triggers require a secret env var name/i)).not.toBeVisible();
    await expect(saveButton).toBeEnabled();
  });

  test("scheduled and file watch triggers validate required fields client-side", async ({ page }) => {
    await page.goto(`/procedures/${PROC_ID}/${VERSION}?tab=trigger`);

    const typeSelect = page.getByLabel(/Trigger Type/i);
    const saveButton = page.getByRole("button", { name: /Register Trigger|Update Trigger/i });

    await typeSelect.selectOption("scheduled");
    await expect(page.getByText(/Scheduled triggers require a cron expression/i)).toBeVisible();
    await expect(saveButton).toBeDisabled();

    await page.getByLabel(/Cron Expression/i).fill("bad cron");
    await expect(page.getByText(/Cron expression must contain exactly 5 UTC fields/i)).toBeVisible();
    await expect(saveButton).toBeDisabled();

    await page.getByLabel(/Cron Expression/i).fill("0 9 * * 1-5");
    await expect(page.getByText(/Cron expression must contain exactly 5 UTC fields/i)).not.toBeVisible();
    await expect(saveButton).toBeEnabled();

    await typeSelect.selectOption("file_watch");
    await expect(page.getByText(/File watch triggers require a watched file path/i)).toBeVisible();
    await expect(saveButton).toBeDisabled();

    await page.getByLabel(/Watch Path/i).fill("C:/data/inbox/orders.json");
    await expect(page.getByText(/File watch triggers require a watched file path/i)).not.toBeVisible();
    await expect(saveButton).toBeEnabled();
  });

  test("valid scheduled trigger can be saved and shows active registration details", async ({ page }) => {
    await page.goto(`/procedures/${PROC_ID}/${VERSION}?tab=trigger`);

    await page.getByLabel(/Trigger Type/i).selectOption("scheduled");
    await page.getByLabel(/Cron Expression/i).fill("0 9 * * 1-5");

    const saveButton = page.getByRole("button", { name: /Register Trigger|Update Trigger/i });
    await expect(saveButton).toBeEnabled();
    await saveButton.click();

    await expect(page.getByText(/Trigger saved/i)).toBeVisible();
    await expect(page.getByText(/^Active$/i)).toBeVisible();
    await expect(page.getByText(/Schedule:/i)).toBeVisible();
    await expect(page.getByText("0 9 * * 1-5")).toBeVisible();
    await expect(page.getByRole("button", { name: /Update Trigger/i })).toBeVisible();
  });
});