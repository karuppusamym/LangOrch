import { test, expect } from "@playwright/test";

import {
  authenticatePage,
  createCaseRecord,
  createProjectRecord,
  deleteCaseRecord,
  deleteCaseSlaPolicyRecord,
  deleteCaseWebhookRecord,
  deleteProjectRecord,
  forceCaseWebhookDeliveriesFailed,
  getCaseWebhookDlqCountForCase,
  importProcedure,
  listCaseSlaPoliciesForProject,
  listCaseWebhookDeliveriesForCase,
  listCaseWebhooksForProject,
  deleteProcedure,
  waitForCaseWebhookDeliveries,
  waitForBackend,
} from "./helpers";

function uid(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function parseTimestamp(value: string): Date {
  return new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`);
}

function minutesUntil(iso: string): number {
  return (parseTimestamp(iso).getTime() - Date.now()) / 60_000;
}

test.describe("Cases page", () => {
  test.beforeAll(async ({ request }) => {
    await waitForBackend(request);
  });

  test.beforeEach(async ({ page, request }) => {
    await authenticatePage(page, request);
  });

  test("real-time case and queue example supports claim and release", async ({ page, request }) => {
    const project = await createProjectRecord(request, {
      name: uid("Queue E2E Project"),
      description: "Queue and case real-time example",
    });
    const createdCaseIds: string[] = [];

    try {
      const urgentCase = await createCaseRecord(request, {
        title: uid("VIP outage"),
        project_id: project.project_id,
        case_type: "incident",
        priority: "urgent",
        metadata: { source: "realtime-example", channel: "queue" },
      });
      const normalCase = await createCaseRecord(request, {
        title: uid("Standard follow-up"),
        project_id: project.project_id,
        case_type: "incident",
        priority: "normal",
      });
      createdCaseIds.push(urgentCase.case_id, normalCase.case_id);

      await page.goto("/cases?tab=queue");
      await expect(page.getByRole("heading", { name: "Cases" })).toBeVisible();

      await page.getByRole("combobox", { name: /Filter queue by project/i }).selectOption({ label: project.name });

      const queueTable = page.locator("table").last();
      const urgentRow = queueTable.getByRole("row").filter({ has: page.getByText(urgentCase.title, { exact: true }) });
      const normalRow = queueTable.getByRole("row").filter({ has: page.getByText(normalCase.title, { exact: true }) });

      await expect(urgentRow).toBeVisible();
      await expect(normalRow).toBeVisible();
      await expect(queueTable.locator("tbody tr").first()).toContainText(urgentCase.title);
      await expect(page.getByText("Active Cases").locator("..")).toContainText("2");

      await page.getByPlaceholder("Claim owner").fill("queue_worker_e2e");
      await urgentRow.getByRole("button", { name: /^Claim$/i }).click();
      await expect(urgentRow).toContainText("queue_worker_e2e");
      await expect(urgentRow.getByRole("button", { name: /^Release$/i })).toBeVisible();

      await urgentRow.getByRole("button", { name: /^Release$/i }).click();
      await expect(urgentRow.getByRole("button", { name: /^Claim$/i })).toBeVisible();
      await expect(page.getByText("Unassigned: 2")).toBeVisible();
    } finally {
      for (const caseId of createdCaseIds) {
        await deleteCaseRecord(request, caseId);
      }
      await deleteProjectRecord(request, project.project_id);
    }
  });

  test("SLA policy tab creates a policy and new matching cases get an SLA due time", async ({ page, request }) => {
    const project = await createProjectRecord(request, {
      name: uid("SLA E2E Project"),
      description: "SLA policy example",
    });
    const createdCaseIds: string[] = [];
    const createdPolicyIds: string[] = [];
    const policyName = uid("Incident High 30m");
    const caseType = uid("sla_case_type");

    try {
      await page.goto("/cases?tab=sla");
      await expect(page.getByRole("heading", { name: "Cases" })).toBeVisible();

      await page.getByPlaceholder("Name *").fill(policyName);
      await page.getByRole("combobox", { name: /New policy project/i }).selectOption({ label: project.name });
      await page.getByPlaceholder("Case type").fill(caseType);
      await page.getByPlaceholder("Priority").fill("high");
      await page.getByPlaceholder("Due minutes").fill("30");
      await page.getByPlaceholder("Breach status").fill("escalated");
      await page.getByRole("button", { name: /Create Policy/i }).click();

      const policyRow = page.getByRole("row").filter({ has: page.getByText(policyName, { exact: true }) });
      await expect(policyRow).toBeVisible();
      await expect(policyRow).toContainText("30m");
      await expect(policyRow).toContainText(project.project_id);
      await expect(policyRow).toContainText(caseType);

      const policies = await listCaseSlaPoliciesForProject(request, project.project_id);
      const createdPolicy = policies.find((policy) => policy.name === policyName);
      expect(createdPolicy).toBeTruthy();
      if (createdPolicy) {
        expect(createdPolicy.due_minutes).toBe(30);
        createdPolicyIds.push(createdPolicy.policy_id);
      }

      const createdCase = await createCaseRecord(request, {
        title: uid("SLA matched case"),
        project_id: project.project_id,
        case_type: caseType,
        priority: "high",
      });
      createdCaseIds.push(createdCase.case_id);

      expect(createdCase.sla_due_at).toBeTruthy();
      if (createdCase.sla_due_at) {
        const dueMinutes = minutesUntil(createdCase.sla_due_at);
        expect(dueMinutes).toBeGreaterThanOrEqual(25);
        expect(dueMinutes).toBeLessThanOrEqual(35);
      }
    } finally {
      for (const caseId of createdCaseIds) {
        await deleteCaseRecord(request, caseId);
      }
      for (const policyId of createdPolicyIds) {
        await deleteCaseSlaPolicyRecord(request, policyId);
      }
      await deleteProjectRecord(request, project.project_id);
    }
  });

  test("webhook tab creates a subscription and shows case-scoped delivery totals", async ({ page, request }) => {
    const project = await createProjectRecord(request, {
      name: uid("Webhook E2E Project"),
      description: "Webhook example",
    });
    const createdCaseIds: string[] = [];
    const createdWebhookIds: string[] = [];
    const webhookUrl = `https://${uid("case-webhook")}.invalid/hook`;

    try {
      await page.goto("/cases?tab=webhooks");
      await expect(page.getByRole("heading", { name: "Cases" })).toBeVisible();

      await page.getByRole("combobox", { name: /Webhook event type/i }).selectOption("case_created");
      await page.getByPlaceholder("Target URL *").fill(webhookUrl);
      await page.getByRole("combobox", { name: /New webhook project/i }).selectOption({ label: project.name });
      await page.getByPlaceholder("Secret env var").fill("CASE_WEBHOOK_SECRET");
      await page.getByRole("button", { name: /Create Webhook/i }).click();

      const webhookRow = page.getByRole("row").filter({ has: page.getByText(webhookUrl, { exact: true }) });
      await expect(webhookRow).toBeVisible();

      const webhooks = await listCaseWebhooksForProject(request, project.project_id);
      const createdWebhook = webhooks.find((webhook) => webhook.target_url === webhookUrl);
      expect(createdWebhook).toBeTruthy();
      if (createdWebhook) {
        createdWebhookIds.push(createdWebhook.subscription_id);
      }

      const createdCase = await createCaseRecord(request, {
        title: uid("Webhook case"),
        project_id: project.project_id,
        case_type: "incident",
        priority: "high",
      });
      createdCaseIds.push(createdCase.case_id);

      await expect.poll(async () => {
        const deliveries = await listCaseWebhookDeliveriesForCase(request, createdCase.case_id);
        return deliveries.filter((delivery) => delivery.case_id === createdCase.case_id).length;
      }, { timeout: 10_000 }).toBeGreaterThan(0);

      const expectedDeliveryCount = (
        await listCaseWebhookDeliveriesForCase(request, createdCase.case_id)
      ).filter((delivery) => delivery.case_id === createdCase.case_id).length;

      await page.getByRole("combobox", { name: /Filter webhooks by project/i }).selectOption({ label: project.name });
      await page.getByPlaceholder("Filter case_id").fill(createdCase.case_id);

      await expect.poll(async () => {
        const cardText = await page.getByText("Deliveries Total").locator("..").textContent();
        const match = cardText?.match(/\d+/);
        return match ? Number(match[0]) : 0;
      }, { timeout: 10_000 }).toBe(expectedDeliveryCount);
    } finally {
      for (const caseId of createdCaseIds) {
        await deleteCaseRecord(request, caseId);
      }
      for (const webhookId of createdWebhookIds) {
        await deleteCaseWebhookRecord(request, webhookId);
      }
      await deleteProjectRecord(request, project.project_id);
    }
  });

  test("webhook DLQ replay selected updates the row out of failed state", async ({ page, request }) => {
    const project = await createProjectRecord(request, {
      name: uid("Webhook DLQ Replay Project"),
      description: "Replay selected DLQ example",
    });
    const createdCaseIds: string[] = [];
    const createdWebhookIds: string[] = [];
    const webhookUrl = `https://${uid("case-dlq-replay")}.invalid/hook`;

    try {
      const webhook = await request.post(`${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/cases/webhooks`, {
        data: {
          event_type: "case_created",
          target_url: webhookUrl,
          project_id: project.project_id,
          enabled: true,
        },
        headers: { "Content-Type": "application/json" },
      });
      expect(webhook.ok(), `Create webhook failed: ${await webhook.text()}`).toBeTruthy();
      const webhookPayload = await webhook.json();
      createdWebhookIds.push(webhookPayload.subscription_id);

      const createdCase = await createCaseRecord(request, {
        title: uid("DLQ replay case"),
        project_id: project.project_id,
        case_type: "incident",
        priority: "high",
      });
      createdCaseIds.push(createdCase.case_id);

      await waitForCaseWebhookDeliveries(request, createdCase.case_id, 1);
      forceCaseWebhookDeliveriesFailed(createdCase.case_id, "HTTP 503", 503);

      await expect.poll(async () => getCaseWebhookDlqCountForCase(request, createdCase.case_id), { timeout: 10_000 }).toBe(1);

      await page.goto("/cases?tab=webhooks");
      await page.getByRole("combobox", { name: /Filter webhooks by project/i }).selectOption({ label: project.name });
      await page.getByPlaceholder("Filter case_id").fill(createdCase.case_id);

      const dlqTable = page.locator("table").last();
      const dlqRow = dlqTable.getByRole("row").filter({ has: page.getByText(createdCase.case_id, { exact: true }) });
      await expect(dlqRow).toBeVisible();
      await dlqRow.getByRole("checkbox").check();
      await expect(page.getByRole("button", { name: /Replay Selected \(1\)/i })).toBeEnabled();

      await page.getByRole("button", { name: /Replay Selected \(1\)/i }).click();
      await expect(page.getByText(/Replayed 1/i)).toBeVisible();
      await expect(dlqRow).not.toBeVisible({ timeout: 10_000 });
      await expect.poll(async () => getCaseWebhookDlqCountForCase(request, createdCase.case_id), { timeout: 10_000 }).toBe(0);
    } finally {
      for (const caseId of createdCaseIds) {
        await deleteCaseRecord(request, caseId);
      }
      for (const webhookId of createdWebhookIds) {
        await deleteCaseWebhookRecord(request, webhookId);
      }
      await deleteProjectRecord(request, project.project_id);
    }
  });

  test("webhook DLQ purge selected removes the failed delivery row", async ({ page, request }) => {
    const project = await createProjectRecord(request, {
      name: uid("Webhook DLQ Purge Project"),
      description: "Purge selected DLQ example",
    });
    const createdCaseIds: string[] = [];
    const createdWebhookIds: string[] = [];
    const webhookUrl = `https://${uid("case-dlq-purge")}.invalid/hook`;

    try {
      const webhook = await request.post(`${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/cases/webhooks`, {
        data: {
          event_type: "case_created",
          target_url: webhookUrl,
          project_id: project.project_id,
          enabled: true,
        },
        headers: { "Content-Type": "application/json" },
      });
      expect(webhook.ok(), `Create webhook failed: ${await webhook.text()}`).toBeTruthy();
      const webhookPayload = await webhook.json();
      createdWebhookIds.push(webhookPayload.subscription_id);

      const createdCase = await createCaseRecord(request, {
        title: uid("DLQ purge case"),
        project_id: project.project_id,
        case_type: "incident",
        priority: "high",
      });
      createdCaseIds.push(createdCase.case_id);

      await waitForCaseWebhookDeliveries(request, createdCase.case_id, 1);
      forceCaseWebhookDeliveriesFailed(createdCase.case_id, "HTTP 500", 500);

      await expect.poll(async () => getCaseWebhookDlqCountForCase(request, createdCase.case_id), { timeout: 10_000 }).toBe(1);

      await page.goto("/cases?tab=webhooks");
      await page.getByRole("combobox", { name: /Filter webhooks by project/i }).selectOption({ label: project.name });
      await page.getByPlaceholder("Filter case_id").fill(createdCase.case_id);

      const dlqTable = page.locator("table").last();
      const dlqRow = dlqTable.getByRole("row").filter({ has: page.getByText(createdCase.case_id, { exact: true }) });
      await expect(dlqRow).toBeVisible();
      await dlqRow.getByRole("checkbox").check();
      await expect(page.getByRole("button", { name: /Purge Selected \(1\)/i })).toBeEnabled();

      page.once("dialog", (dialog) => dialog.accept());
      await page.getByRole("button", { name: /Purge Selected \(1\)/i }).click();
      await expect(page.getByText(/Purged 1/i)).toBeVisible();
      await expect(dlqRow).not.toBeVisible({ timeout: 10_000 });
      await expect.poll(async () => getCaseWebhookDlqCountForCase(request, createdCase.case_id), { timeout: 10_000 }).toBe(0);
    } finally {
      for (const caseId of createdCaseIds) {
        await deleteCaseRecord(request, caseId);
      }
      for (const webhookId of createdWebhookIds) {
        await deleteCaseWebhookRecord(request, webhookId);
      }
      await deleteProjectRecord(request, project.project_id);
    }
  });

  test("case details can start a linked run and show it in the timeline panel", async ({ page, request }) => {
    const project = await createProjectRecord(request, {
      name: uid("Case Run Project"),
      description: "Case linked run example",
    });
    const createdCaseIds: string[] = [];
    const procedureId = "e2e_test_procedure";
    const procedureVersion = "1.0.0";

    try {
      await importProcedure(request, "sample.procedure.json", project.project_id);

      const createdCase = await createCaseRecord(request, {
        title: uid("Case linked run"),
        project_id: project.project_id,
        case_type: "incident",
        priority: "high",
      });
      createdCaseIds.push(createdCase.case_id);

      await page.goto("/cases");
      await expect(page.getByRole("heading", { name: "Cases" })).toBeVisible();

      const caseRow = page.getByRole("row").filter({ has: page.getByText(createdCase.title, { exact: true }) });
      await expect(caseRow).toBeVisible();
      await caseRow.getByRole("button", { name: createdCase.title, exact: true }).click();

      const panel = page.getByText("Case Timeline").locator("..");
      await expect(panel).toContainText(createdCase.case_id);

      await page.getByRole("combobox", { name: /Select procedure for case run/i }).selectOption(`${procedureId}::${procedureVersion}`);
      await page.getByRole("button", { name: /^Start Run$/i }).first().click();

      await expect(page.getByText(/Review Run Variables|required field/i)).toBeVisible();
      await page.locator("div.fixed.inset-0").getByRole("button", { name: /^Start Run$/i }).click();
      await expect(page.getByText(/Run started for case:/i)).toBeVisible();

      let linkedRunId: string | null = null;
      await expect.poll(async () => {
        const response = await request.get(`${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/runs?case_id=${encodeURIComponent(createdCase.case_id)}&limit=5`);
        expect(response.ok(), `List runs failed: ${await response.text()}`).toBeTruthy();
        const runs = await response.json();
        linkedRunId = runs[0]?.run_id ?? null;
        return linkedRunId;
      }, { timeout: 10_000 }).not.toBeNull();

      await expect(panel.getByText("Runs (1)")).toBeVisible({ timeout: 10_000 });
      await expect(panel.getByText(linkedRunId!)).toBeVisible({ timeout: 10_000 });
      await expect(panel.getByText("run_linked")).toBeVisible({ timeout: 10_000 });
    } finally {
      for (const caseId of createdCaseIds) {
        await deleteCaseRecord(request, caseId);
      }
      await deleteProcedure(request, procedureId, procedureVersion);
      await deleteProjectRecord(request, project.project_id);
    }
  });
});