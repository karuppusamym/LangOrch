/* API client — all backend calls go through here */

import type {
  Artifact,
  Procedure,
  ProcedureDetail,
  Project,
  Run,
  RunEvent,
  Approval,
  AgentInstance,
  RunDiagnostics,
  MetricsSummary,
  CheckpointMetadata,
  CheckpointState,
  ExplainReport,
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
  // 204 No Content — no body to parse
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as unknown as T;
  }
  return res.json();
}

/* ── Procedures ────────────────────────── */

export async function listProcedures(params?: {
  status?: string;
  tags?: string[];
  project_id?: string;
}): Promise<Procedure[]> {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.tags?.length) q.set("tags", params.tags.join(","));
  if (params?.project_id) q.set("project_id", params.project_id);
  const qs = q.toString();
  return request(`/procedures${qs ? `?${qs}` : ""}`);
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

export async function importProcedure(
  ckpJson: Record<string, unknown>,
  projectId?: string
): Promise<Procedure> {
  return request("/procedures", {
    method: "POST",
    body: JSON.stringify({ ckp_json: ckpJson, project_id: projectId ?? null }),
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
  limit?: number;
  offset?: number;
}): Promise<Run[]> {
  const q = new URLSearchParams();
  if (params?.status && params.status !== "all") q.set("status", params.status);
  if (params?.createdFrom) q.set("created_from", params.createdFrom);
  if (params?.createdTo) q.set("created_to", params.createdTo);
  if (params?.order) q.set("order", params.order);
  if (params?.limit !== undefined) q.set("limit", String(params.limit));
  if (params?.offset !== undefined) q.set("offset", String(params.offset));
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
  capabilities?: string[];
}): Promise<AgentInstance> {
  return request("/agents", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateAgent(
  agentId: string,
  data: { status?: string; base_url?: string; concurrency_limit?: number; capabilities?: string[] }
): Promise<AgentInstance> {
  return request(`/agents/${encodeURIComponent(agentId)}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteAgent(agentId: string): Promise<void> {
  await request(`/agents/${encodeURIComponent(agentId)}`, { method: "DELETE" });
}

export async function syncAgentCapabilities(agentId: string): Promise<AgentInstance> {
  return request(`/agents/${encodeURIComponent(agentId)}/sync-capabilities`, { method: "POST" });
}

export async function probeAgentCapabilities(baseUrl: string): Promise<string[]> {
  return request(`/agents/probe-capabilities?base_url=${encodeURIComponent(baseUrl)}`);
}

export async function getActionCatalog(): Promise<Record<string, string[]>> {
  return request("/actions");
}

/* ── Projects ──────────────────────────────────── */

export async function listProjects(): Promise<Project[]> {
  return request("/projects");
}

export async function createProject(data: { name: string; description?: string }): Promise<Project> {
  return request("/projects", { method: "POST", body: JSON.stringify(data) });
}

export async function updateProject(
  projectId: string,
  data: { name?: string; description?: string }
): Promise<Project> {
  return request(`/projects/${encodeURIComponent(projectId)}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteProject(projectId: string): Promise<void> {
  await request(`/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
}

/* ── Diagnostics & Metrics ────────────────── */

export async function getRunDiagnostics(runId: string): Promise<RunDiagnostics> {
  return request(`/runs/${runId}/diagnostics`);
}

export async function getMetricsSummary(): Promise<MetricsSummary> {
  return request("/runs/metrics/summary");
}

/* ── Leases ────────────────────────────── */

export async function listLeases(resourceKey?: string): Promise<import("./types").ResourceLeaseDiagnostic[]> {
  const q = resourceKey ? `?resource_key=${encodeURIComponent(resourceKey)}` : "";
  return request(`/leases${q}`);
}

export async function revokeLease(leaseId: string): Promise<void> {
  await request(`/leases/${leaseId}`, { method: "DELETE" });
}

/* ── Checkpoints ───────────────────────── */

export async function listRunCheckpoints(runId: string): Promise<CheckpointMetadata[]> {
  return request(`/runs/${runId}/checkpoints`);
}

export async function getCheckpointState(
  runId: string,
  checkpointId: string
): Promise<CheckpointState> {
  return request(`/runs/${runId}/checkpoints/${encodeURIComponent(checkpointId)}`);
}

/* ── Explain (static analysis) ─────────── */

export async function explainProcedure(
  procedureId: string,
  version: string,
  inputVars?: Record<string, unknown>
): Promise<ExplainReport> {
  return request(
    `/procedures/${encodeURIComponent(procedureId)}/${encodeURIComponent(version)}/explain`,
    {
      method: "POST",
      body: JSON.stringify({ input_vars: inputVars ?? {} }),
    }
  );
}
