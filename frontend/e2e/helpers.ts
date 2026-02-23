/**
 * Shared helpers for LangOrch e2e tests.
 *
 * All helpers communicate with the backend API directly via Playwright's
 * `request` context so we can set up and tear down test data without going
 * through the UI.
 */

import { APIRequestContext, expect } from "@playwright/test";
import * as path from "path";
import * as fs from "fs";

export const BACKEND_BASE = process.env.BACKEND_URL ?? "http://localhost:8000";
const API = `${BACKEND_BASE}/api`;

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
