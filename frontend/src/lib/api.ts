/* API client — all backend calls go through here */

import type {
  Artifact,
  Procedure,
  ProcedureDetail,
  Run,
  RunEvent,
  Approval,
  AgentInstance,
  ActionCatalog,
} from "./types";

const API_BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

/* ── Procedures ────────────────────────── */

export async function listProcedures(): Promise<Procedure[]> {
  return request("/procedures");
}

export async function getProcedure(id: string, version?: string): Promise<ProcedureDetail> {
  if (version) {
    return request(`/procedures/${encodeURIComponent(id)}/${encodeURIComponent(version)}`);
  }

  const versions = await listVersions(id);
  if (!versions.length) {
    throw new Error(`Procedure not found: ${id}`);
  }

  return request(
    `/procedures/${encodeURIComponent(id)}/${encodeURIComponent(versions[0].version)}`
  );
}

export async function importProcedure(ckpJson: Record<string, unknown>): Promise<Procedure> {
  return request("/procedures", {
    method: "POST",
    body: JSON.stringify({ ckp_json: ckpJson }),
  });
}

export async function listVersions(id: string): Promise<Procedure[]> {
  return request(`/procedures/${id}/versions`);
}

export async function updateProcedure(
  id: string,
  version: string,
  ckpJson: Record<string, unknown>
): Promise<Procedure> {
  return request(`/procedures/${encodeURIComponent(id)}/${encodeURIComponent(version)}`, {
    method: "PUT",
    body: JSON.stringify({ ckp_json: ckpJson }),
  });
}

export async function deleteProcedure(id: string, version: string): Promise<void> {
  await request(`/procedures/${encodeURIComponent(id)}/${encodeURIComponent(version)}`, {
    method: "DELETE",
  });
}

export async function getGraph(
  id: string,
  version: string
): Promise<{ nodes: unknown[]; edges: unknown[] }> {
  return request(
    `/procedures/${encodeURIComponent(id)}/${encodeURIComponent(version)}/graph`
  );
}

/* ── Runs ──────────────────────────────── */

export async function listRuns(params?: {
  status?: string;
  createdFrom?: string;
  createdTo?: string;
  order?: "asc" | "desc";
}): Promise<Run[]> {
  const q = new URLSearchParams();
  if (params?.status && params.status !== "all") q.set("status", params.status);
  if (params?.createdFrom) q.set("created_from", params.createdFrom);
  if (params?.createdTo) q.set("created_to", params.createdTo);
  if (params?.order) q.set("order", params.order);
  const qs = q.toString();
  return request(`/runs${qs ? `?${qs}` : ""}`);
}

export async function getRun(id: string): Promise<Run> {
  return request(`/runs/${id}`);
}

export async function createRun(
  procedureId: string,
  version: string,
  inputVars?: Record<string, unknown>
): Promise<Run> {
  return request("/runs", {
    method: "POST",
    body: JSON.stringify({
      procedure_id: procedureId,
      procedure_version: version,
      input_vars: inputVars ?? {},
    }),
  });
}

export async function cancelRun(id: string): Promise<void> {
  await request(`/runs/${id}/cancel`, { method: "POST" });
}

export async function retryRun(id: string): Promise<Run> {
  return request(`/runs/${id}/retry`, { method: "POST" });
}

export async function deleteRun(id: string): Promise<void> {
  await request(`/runs/${id}`, { method: "DELETE" });
}

export async function cleanupRuns(beforeIso: string, status?: string): Promise<{ deleted_count: number }> {
  const q = new URLSearchParams({ before: beforeIso });
  if (status && status !== "all") q.set("status", status);
  return request(`/runs/cleanup/history?${q.toString()}`, { method: "DELETE" });
}

/* ── Events ────────────────────────────── */

export async function listRunEvents(runId: string): Promise<RunEvent[]> {
  return request(`/runs/${runId}/events`);
}

export async function listRunArtifacts(runId: string): Promise<Artifact[]> {
  return request(`/runs/${runId}/artifacts`);
}

/* ── Approvals ─────────────────────────── */
export async function listApprovals(): Promise<Approval[]> {
  return request("/approvals");
}

export async function getApproval(id: string): Promise<Approval> {
  return request(`/approvals/${id}`);
}

export async function submitApprovalDecision(
  id: string,
  decision: "approved" | "rejected",
  decidedBy: string,
  comment?: string
): Promise<Approval> {
  return request(`/approvals/${id}/decision`, {
    method: "POST",
    body: JSON.stringify({
      status: decision,
      decided_by: decidedBy,
      comment,
    }),
  });
}

/* ── Agents ────────────────────────────── */

export async function listAgents(): Promise<AgentInstance[]> {
  return request("/agents");
}

export async function registerAgent(data: {
  agent_id: string;
  name: string;
  channel: string;
  base_url: string;
  resource_key?: string;
  concurrency_limit?: number;
}): Promise<AgentInstance> {
  return request("/agents", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/* ── Catalog ───────────────────────────── */

export async function getActionCatalog(): Promise<ActionCatalog> {
  return request("/actions");
}
