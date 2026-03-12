/**
 * Shared helpers for LangOrch e2e tests.
 *
 * All helpers communicate with the backend API directly via Playwright's
 * `request` context so we can set up and tear down test data without going
 * through the UI.
 */

import { APIRequestContext, expect, Page } from "@playwright/test";
import * as path from "path";
import * as fs from "fs";
import { spawnSync } from "child_process";

export const BACKEND_BASE = process.env.BACKEND_URL ?? "http://localhost:8000";
export const FRONTEND_BASE = process.env.BASE_URL ?? "http://localhost:3000";
const API = `${BACKEND_BASE}/api`;
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const BACKEND_ROOT = path.resolve(REPO_ROOT, "backend");
const BACKEND_DB_PATH = path.resolve(BACKEND_ROOT, "langorch.db");
const BACKEND_PYTHON = path.resolve(BACKEND_ROOT, ".venv", "Scripts", "python.exe");

type LoginResponse = {
  access_token: string;
  identity: string;
  roles: string[];
  user_id?: string;
  email?: string;
  full_name?: string;
};

type ProjectRecord = {
  project_id: string;
  name: string;
  description: string | null;
};

type CaseRecord = {
  case_id: string;
  project_id: string | null;
  case_type: string | null;
  title: string;
  status: string;
  priority: string;
  owner: string | null;
  sla_due_at: string | null;
};

type CaseSlaPolicyRecord = {
  policy_id: string;
  name: string;
  due_minutes: number;
  enabled: boolean;
};

type CaseWebhookSubscriptionRecord = {
  subscription_id: string;
  event_type: string;
  target_url: string;
  project_id: string | null;
  enabled: boolean;
};

type CaseWebhookDeliveryRecord = {
  delivery_id: string;
  case_id: string | null;
  event_type: string;
  status: string;
};

type CaseWebhookDeliveryCount = {
  total: number;
};

// ─── backend readiness ────────────────────────────────────────────────────────

/** Wait until the backend /api/health returns 200. */
export async function waitForBackend(
  request: APIRequestContext,
  maxWaitMs = 20_000
): Promise<void> {
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    try {
      const res = await request.get(`${BACKEND_BASE}/api/health`);
      if (res.ok()) return;
    } catch {
      // backend not yet ready
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Backend did not become ready within ${maxWaitMs}ms`);
}

// ─── procedure helpers ────────────────────────────────────────────────────────

export function loadFixture(name: string): Record<string, unknown> {
  const p = path.resolve(__dirname, "fixtures", name);
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

export async function loginAsAdmin(
  request: APIRequestContext,
  username = process.env.E2E_USERNAME ?? "admin",
  password = process.env.E2E_PASSWORD ?? "admin123"
): Promise<LoginResponse> {
  const res = await request.post(`${API}/auth/login`, {
    data: { username, password },
    headers: { "Content-Type": "application/json" },
  });
  expect(res.ok(), `Login failed: ${await res.text()}`).toBeTruthy();
  return res.json();
}

export async function authenticatePage(page: Page, request: APIRequestContext): Promise<void> {
  const session = await loginAsAdmin(request);
  const user = {
    identity: session.identity,
    roles: session.roles,
    role: session.roles[session.roles.length - 1] ?? "admin",
    user_id: session.user_id,
    email: session.email,
    full_name: session.full_name,
  };

  await page.addInitScript((authState) => {
    window.localStorage.setItem("langorch_token", authState.token);
    window.localStorage.setItem("langorch_user", JSON.stringify(authState.user));
  }, { token: session.access_token, user });
}

/** Import (upsert) a procedure from a fixture file. Returns the procedure object. */
export async function importProcedure(
  request: APIRequestContext,
  fixtureName: string,
  projectId?: string
): Promise<{ procedure_id: string; version: string; status: string }> {
  const ckpJson = loadFixture(fixtureName);
  const body: Record<string, unknown> = { ckp_json: ckpJson };
  if (projectId) body.project_id = projectId;

  const res = await request.post(`${API}/procedures`, {
    data: body,
    headers: { "Content-Type": "application/json" },
  });
  expect(res.ok(), `Import ${fixtureName}: ${await res.text()}`).toBeTruthy();
  return res.json();
}

/** Start a run for the given procedure_id + version. */
export async function startRun(
  request: APIRequestContext,
  procedureId: string,
  version: string,
  inputVars: Record<string, unknown> = {}
): Promise<{ run_id: string; status: string }> {
  const res = await request.post(`${API}/runs`, {
    data: { procedure_id: procedureId, version, input_vars: inputVars },
    headers: { "Content-Type": "application/json" },
  });
  expect(res.ok(), `Start run ${procedureId}: ${await res.text()}`).toBeTruthy();
  return res.json();
}

/** Poll run status until it is terminal or timeout. */
export async function waitForRun(
  request: APIRequestContext,
  runId: string,
  terminalStatuses = ["completed", "failed", "canceled"],
  maxWaitMs = 30_000
): Promise<{ run_id: string; status: string }> {
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    const res = await request.get(`${API}/runs/${runId}`);
    if (res.ok()) {
      const data = await res.json();
      if (terminalStatuses.includes(data.status)) return data;
    }
    await new Promise((r) => setTimeout(r, 1_000));
  }
  throw new Error(`Run ${runId} did not reach a terminal state in ${maxWaitMs}ms`);
}

/** Fetch all pending approvals for a run. */
export async function getPendingApprovals(
  request: APIRequestContext,
  runId?: string
): Promise<Array<{ approval_id: string; status: string; run_id: string }>> {
  const url = runId
    ? `${API}/approvals?run_id=${runId}`
    : `${API}/approvals?status=pending`;
  const res = await request.get(url);
  expect(res.ok()).toBeTruthy();
  const all: Array<{ approval_id: string; status: string; run_id: string }> = await res.json();
  return all.filter((a) => a.status === "pending");
}

/** Submit an approval decision via the API. */
export async function submitDecision(
  request: APIRequestContext,
  approvalId: string,
  decision: "approved" | "rejected",
  approverName = "e2e_test"
): Promise<void> {
  const res = await request.post(`${API}/approvals/${approvalId}/decision`, {
    data: { decision, approver_name: approverName },
    headers: { "Content-Type": "application/json" },
  });
  expect(res.ok(), `Decision ${decision}: ${await res.text()}`).toBeTruthy();
}

/** Delete a procedure (for teardown). */
export async function deleteProcedure(
  request: APIRequestContext,
  procedureId: string,
  version: string
): Promise<void> {
  await request.delete(`${API}/procedures/${procedureId}/${version}`);
}

// ─── cases helpers ───────────────────────────────────────────────────────────

export async function createProjectRecord(
  request: APIRequestContext,
  data: { name: string; description?: string }
): Promise<ProjectRecord> {
  const res = await request.post(`${API}/projects`, {
    data,
    headers: { "Content-Type": "application/json" },
  });
  expect(res.ok(), `Create project failed: ${await res.text()}`).toBeTruthy();
  return res.json();
}

export async function deleteProjectRecord(
  request: APIRequestContext,
  projectId: string
): Promise<void> {
  await request.delete(`${API}/projects/${projectId}`);
}

export async function createCaseRecord(
  request: APIRequestContext,
  data: Record<string, unknown>
): Promise<CaseRecord> {
  const res = await request.post(`${API}/cases`, {
    data,
    headers: { "Content-Type": "application/json" },
  });
  expect(res.ok(), `Create case failed: ${await res.text()}`).toBeTruthy();
  return res.json();
}

export async function deleteCaseRecord(
  request: APIRequestContext,
  caseId: string
): Promise<void> {
  await request.delete(`${API}/cases/${caseId}`);
}

export async function deleteCaseSlaPolicyRecord(
  request: APIRequestContext,
  policyId: string
): Promise<void> {
  await request.delete(`${API}/cases/sla-policies/${policyId}`);
}

export async function deleteCaseWebhookRecord(
  request: APIRequestContext,
  subscriptionId: string
): Promise<void> {
  await request.delete(`${API}/cases/webhooks/${subscriptionId}`);
}

export async function listCaseSlaPoliciesForProject(
  request: APIRequestContext,
  projectId: string
): Promise<CaseSlaPolicyRecord[]> {
  const res = await request.get(`${API}/cases/sla-policies?project_id=${encodeURIComponent(projectId)}`);
  expect(res.ok(), `List SLA policies failed: ${await res.text()}`).toBeTruthy();
  return res.json();
}

export async function listCaseWebhooksForProject(
  request: APIRequestContext,
  projectId: string
): Promise<CaseWebhookSubscriptionRecord[]> {
  const res = await request.get(`${API}/cases/webhooks?project_id=${encodeURIComponent(projectId)}`);
  expect(res.ok(), `List case webhooks failed: ${await res.text()}`).toBeTruthy();
  return res.json();
}

export async function listCaseWebhookDeliveriesForCase(
  request: APIRequestContext,
  caseId: string
): Promise<CaseWebhookDeliveryRecord[]> {
  const res = await request.get(`${API}/cases/webhooks/deliveries?case_id=${encodeURIComponent(caseId)}`);
  expect(res.ok(), `List webhook deliveries failed: ${await res.text()}`).toBeTruthy();
  return res.json();
}

export async function getCaseWebhookDlqCountForCase(
  request: APIRequestContext,
  caseId: string
): Promise<number> {
  const res = await request.get(`${API}/cases/webhooks/dlq/count?case_id=${encodeURIComponent(caseId)}`);
  expect(res.ok(), `Count DLQ deliveries failed: ${await res.text()}`).toBeTruthy();
  const payload: CaseWebhookDeliveryCount = await res.json();
  return payload.total;
}

export async function waitForCaseWebhookDeliveries(
  request: APIRequestContext,
  caseId: string,
  expectedCount = 1,
  maxWaitMs = 10_000
): Promise<CaseWebhookDeliveryRecord[]> {
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    const deliveries = await listCaseWebhookDeliveriesForCase(request, caseId);
    if (deliveries.length >= expectedCount) return deliveries;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Case ${caseId} did not reach ${expectedCount} webhook deliveries in ${maxWaitMs}ms`);
}

export function forceCaseWebhookDeliveriesFailed(caseId: string, lastError = "HTTP 500", lastStatusCode = 500): void {
  const script = `
import sqlite3
from datetime import datetime, timezone

db_path = r"${BACKEND_DB_PATH.replace(/\\/g, "\\\\")}"
case_id = ${JSON.stringify(caseId)}
last_error = ${JSON.stringify(lastError)}
last_status_code = ${JSON.stringify(lastStatusCode)}
now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")

conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute(
    """
    UPDATE case_webhook_deliveries
    SET status = 'failed',
        attempts = CASE WHEN max_attempts > 0 THEN max_attempts ELSE 5 END,
        last_error = ?,
        last_status_code = ?,
        next_attempt_at = ?,
        updated_at = ?
    WHERE case_id = ?
    """,
    (last_error, last_status_code, now, now, case_id),
)
conn.commit()
if cur.rowcount <= 0:
    raise SystemExit(f"No case_webhook_deliveries rows found for case_id={case_id}")
conn.close()
`;

  const result = spawnSync(BACKEND_PYTHON, ["-c", script], {
    cwd: REPO_ROOT,
    encoding: "utf8",
  });

  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || `Failed to mark webhook deliveries failed for ${caseId}`);
  }
}
