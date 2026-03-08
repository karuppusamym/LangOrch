/* API client — all backend calls go through here */

import type {
  Artifact,
  Procedure,
  ProcedureDetail,
  Project,
  Run,
  RunEvent,
  ProcedurePromoteResponse,
  ProcedureRollbackResponse,
  Approval,
  AgentInstance,
  AgentCapability,
  RunDiagnostics,
  MetricsSummary,
  Case,
  CaseEvent,
  CaseQueueItem,
  CaseQueueAnalytics,
  CaseSlaPolicy,
  CaseWebhookDelivery,
  CaseWebhookDeliveryCount,
  CaseWebhookDeliverySummary,
  CaseWebhookPurgeResult,
  CaseWebhookPurgeSelectedResult,
  CaseWebhookReplayResult,
  CaseWebhookSubscription,
  CheckpointMetadata,
  CheckpointState,
  ExplainReport,
  TriggerRegistration,
  User,
  Secret,
} from "./types";
import { getToken } from "./auth";

const API_BASE = "/api";

let queueAnalyticsSupported: boolean | undefined;

export class ApiError extends Error {
  status: number;
  body: string;

  constructor(status: number, body: string) {
    super(`API ${status}: ${body}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export function isNotFoundError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

function emptyQueueAnalytics(): CaseQueueAnalytics {
  return {
    total_active_cases: 0,
    unassigned_cases: 0,
    breached_cases: 0,
    breach_risk_next_window_cases: 0,
    breach_risk_next_window_percent: 0,
    wait_p50_seconds: 0,
    wait_p95_seconds: 0,
    wait_by_priority: {},
    wait_by_case_type: {},
    reassignment_rate_24h: 0,
    abandonment_rate_24h: 0,
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const authHeader: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeader, ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    if (res.status === 401) {
      // Token expired or invalid — redirect to login
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    const body = await res.text();
    throw new ApiError(res.status, body);
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

export async function promoteProcedure(
  id: string,
  version: string,
  targetChannel: "dev" | "qa" | "prod"
): Promise<ProcedurePromoteResponse> {
  return request(`/procedures/${encodeURIComponent(id)}/${encodeURIComponent(version)}/promote`, {
    method: "POST",
    body: JSON.stringify({ target_channel: targetChannel }),
  });
}

export async function rollbackProcedure(
  id: string,
  version: string,
  targetChannel: "dev" | "qa" | "prod",
  rollbackToVersion?: string
): Promise<ProcedureRollbackResponse> {
  const body: { target_channel: "dev" | "qa" | "prod"; rollback_to_version?: string } = {
    target_channel: targetChannel,
  };
  if (rollbackToVersion) body.rollback_to_version = rollbackToVersion;
  return request(`/procedures/${encodeURIComponent(id)}/${encodeURIComponent(version)}/rollback`, {
    method: "POST",
    body: JSON.stringify(body),
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
  procedure_id?: string;
  project_id?: string;
  case_id?: string;
  status?: string;
  createdFrom?: string;
  createdTo?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}): Promise<Run[]> {
  const q = new URLSearchParams();
  if (params?.procedure_id) q.set("procedure_id", params.procedure_id);
  if (params?.project_id) q.set("project_id", params.project_id);
  if (params?.case_id) q.set("case_id", params.case_id);
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
  inputVars?: Record<string, unknown>,
  opts?: { project_id?: string; case_id?: string }
): Promise<Run> {
  return request("/runs", {
    method: "POST",
    body: JSON.stringify({
      procedure_id: procedureId,
      procedure_version: version,
      input_vars: inputVars ?? {},
      project_id: opts?.project_id,
      case_id: opts?.case_id,
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
  capabilities?: AgentCapability[];
}): Promise<AgentInstance> {
  return request("/agents", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateAgent(
  agentId: string,
  data: { status?: string; base_url?: string; concurrency_limit?: number; capabilities?: AgentCapability[] }
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

export async function probeAgentCapabilities(baseUrl: string): Promise<AgentCapability[]> {
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

/* €€ Cases €€ */

export async function listCases(params?: {
  project_id?: string;
  status?: string;
  owner?: string;
  external_ref?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}): Promise<Case[]> {
  const q = new URLSearchParams();
  if (params?.project_id) q.set("project_id", params.project_id);
  if (params?.status) q.set("status", params.status);
  if (params?.owner) q.set("owner", params.owner);
  if (params?.external_ref) q.set("external_ref", params.external_ref);
  if (params?.order) q.set("order", params.order);
  if (params?.limit !== undefined) {
    // Backend validation enforces 1 <= limit <= 500 for /cases.
    const clampedLimit = Math.max(1, Math.min(500, params.limit));
    q.set("limit", String(clampedLimit));
  }
  if (params?.offset !== undefined) q.set("offset", String(params.offset));
  const qs = q.toString();
  return request(`/cases${qs ? `?${qs}` : ""}`);
}

export async function getCase(caseId: string): Promise<Case> {
  return request(`/cases/${encodeURIComponent(caseId)}`);
}

export async function createCase(data: {
  title: string;
  project_id?: string | null;
  external_ref?: string | null;
  case_type?: string | null;
  description?: string | null;
  status?: string;
  priority?: string;
  owner?: string | null;
  sla_due_at?: string | null;
  tags?: string[] | null;
  metadata?: Record<string, unknown> | null;
}): Promise<Case> {
  return request("/cases", { method: "POST", body: JSON.stringify(data) });
}

export async function updateCase(caseId: string, data: Record<string, unknown>): Promise<Case> {
  return request(`/cases/${encodeURIComponent(caseId)}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteCase(caseId: string): Promise<void> {
  await request(`/cases/${encodeURIComponent(caseId)}`, { method: "DELETE" });
}

export async function listCaseEvents(caseId: string, limit = 200): Promise<CaseEvent[]> {
  return request(`/cases/${encodeURIComponent(caseId)}/events?limit=${limit}`);
}

export async function listCaseQueue(params?: {
  project_id?: string;
  owner?: string;
  only_unassigned?: boolean;
  include_terminal?: boolean;
  limit?: number;
  offset?: number;
}): Promise<CaseQueueItem[]> {
  const q = new URLSearchParams();
  if (params?.project_id) q.set("project_id", params.project_id);
  if (params?.owner) q.set("owner", params.owner);
  if (params?.only_unassigned !== undefined) q.set("only_unassigned", String(params.only_unassigned));
  if (params?.include_terminal !== undefined) q.set("include_terminal", String(params.include_terminal));
  if (params?.limit !== undefined) q.set("limit", String(params.limit));
  if (params?.offset !== undefined) q.set("offset", String(params.offset));
  const qs = q.toString();
  return request(`/cases/queue${qs ? `?${qs}` : ""}`);
}

export async function getCaseQueueAnalytics(params?: {
  project_id?: string;
  risk_window_minutes?: number;
}): Promise<CaseQueueAnalytics> {
  if (queueAnalyticsSupported === false) {
    return emptyQueueAnalytics();
  }
  const q = new URLSearchParams();
  if (params?.project_id) q.set("project_id", params.project_id);
  if (params?.risk_window_minutes !== undefined) q.set("risk_window_minutes", String(params.risk_window_minutes));
  const qs = q.toString();
  try {
    const data = await request<CaseQueueAnalytics>(`/cases/queue/analytics${qs ? `?${qs}` : ""}`);
    queueAnalyticsSupported = true;
    return data;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (message.startsWith("API 404:")) {
      // Some running backend instances may not expose this endpoint yet.
      queueAnalyticsSupported = false;
      return emptyQueueAnalytics();
    }
    throw err;
  }
}

export async function claimCase(caseId: string, owner: string, setInProgress = true): Promise<Case> {
  return request(`/cases/${encodeURIComponent(caseId)}/claim`, {
    method: "POST",
    body: JSON.stringify({ owner, set_in_progress: setInProgress }),
  });
}

export async function releaseCase(caseId: string, owner?: string, setOpen = false): Promise<Case> {
  return request(`/cases/${encodeURIComponent(caseId)}/release`, {
    method: "POST",
    body: JSON.stringify({ owner, set_open: setOpen }),
  });
}

export async function listCaseSlaPolicies(params?: {
  project_id?: string;
  case_type?: string;
  priority?: string;
  enabled_only?: boolean;
}): Promise<CaseSlaPolicy[]> {
  const q = new URLSearchParams();
  if (params?.project_id) q.set("project_id", params.project_id);
  if (params?.case_type) q.set("case_type", params.case_type);
  if (params?.priority) q.set("priority", params.priority);
  if (params?.enabled_only !== undefined) q.set("enabled_only", String(params.enabled_only));
  const qs = q.toString();
  return request(`/cases/sla-policies${qs ? `?${qs}` : ""}`);
}

export async function createCaseSlaPolicy(data: {
  name: string;
  project_id?: string | null;
  case_type?: string | null;
  priority?: string | null;
  due_minutes: number;
  breach_status?: string;
  enabled?: boolean;
}): Promise<CaseSlaPolicy> {
  return request("/cases/sla-policies", { method: "POST", body: JSON.stringify(data) });
}

export async function updateCaseSlaPolicy(policyId: string, data: Record<string, unknown>): Promise<CaseSlaPolicy> {
  return request(`/cases/sla-policies/${encodeURIComponent(policyId)}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteCaseSlaPolicy(policyId: string): Promise<void> {
  await request(`/cases/sla-policies/${encodeURIComponent(policyId)}`, { method: "DELETE" });
}

export async function listCaseWebhooks(params?: {
  project_id?: string;
  enabled_only?: boolean;
}): Promise<CaseWebhookSubscription[]> {
  const q = new URLSearchParams();
  if (params?.project_id) q.set("project_id", params.project_id);
  if (params?.enabled_only !== undefined) q.set("enabled_only", String(params.enabled_only));
  const qs = q.toString();
  return request(`/cases/webhooks${qs ? `?${qs}` : ""}`);
}

export async function createCaseWebhook(data: {
  event_type: string;
  target_url: string;
  project_id?: string | null;
  secret_env_var?: string | null;
  enabled?: boolean;
}): Promise<CaseWebhookSubscription> {
  return request("/cases/webhooks", { method: "POST", body: JSON.stringify(data) });
}

export async function deleteCaseWebhook(subscriptionId: string): Promise<void> {
  await request(`/cases/webhooks/${encodeURIComponent(subscriptionId)}`, { method: "DELETE" });
}

export async function listCaseWebhookDeliveries(params?: {
  status?: "pending" | "processing" | "retrying" | "delivered" | "failed";
  subscription_id?: string;
  case_id?: string;
  event_type?: string;
  sort_by?: "created_at" | "updated_at" | "attempts";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}): Promise<CaseWebhookDelivery[]> {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.subscription_id) q.set("subscription_id", params.subscription_id);
  if (params?.case_id) q.set("case_id", params.case_id);
  if (params?.event_type) q.set("event_type", params.event_type);
  if (params?.sort_by) q.set("sort_by", params.sort_by);
  if (params?.order) q.set("order", params.order);
  if (params?.limit !== undefined) q.set("limit", String(params.limit));
  if (params?.offset !== undefined) q.set("offset", String(params.offset));
  const qs = q.toString();
  return request(`/cases/webhooks/deliveries${qs ? `?${qs}` : ""}`);
}

export async function listCaseWebhookDlq(params?: {
  subscription_id?: string;
  case_id?: string;
  event_type?: string;
  sort_by?: "created_at" | "updated_at" | "attempts";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}): Promise<CaseWebhookDelivery[]> {
  const q = new URLSearchParams();
  if (params?.subscription_id) q.set("subscription_id", params.subscription_id);
  if (params?.case_id) q.set("case_id", params.case_id);
  if (params?.event_type) q.set("event_type", params.event_type);
  if (params?.sort_by) q.set("sort_by", params.sort_by);
  if (params?.order) q.set("order", params.order);
  if (params?.limit !== undefined) q.set("limit", String(params.limit));
  if (params?.offset !== undefined) q.set("offset", String(params.offset));
  const qs = q.toString();
  return request(`/cases/webhooks/dlq${qs ? `?${qs}` : ""}`);
}

export async function getCaseWebhookDlqCount(params?: {
  subscription_id?: string;
  case_id?: string;
  event_type?: string;
  older_than_hours?: number;
}): Promise<CaseWebhookDeliveryCount> {
  const q = new URLSearchParams();
  if (params?.subscription_id) q.set("subscription_id", params.subscription_id);
  if (params?.case_id) q.set("case_id", params.case_id);
  if (params?.event_type) q.set("event_type", params.event_type);
  if (params?.older_than_hours !== undefined) q.set("older_than_hours", String(params.older_than_hours));
  const qs = q.toString();
  return request(`/cases/webhooks/dlq/count${qs ? `?${qs}` : ""}`);
}

export async function getCaseWebhookDeliverySummary(params?: {
  subscription_id?: string;
  case_id?: string;
  event_type?: string;
}): Promise<CaseWebhookDeliverySummary> {
  const q = new URLSearchParams();
  if (params?.subscription_id) q.set("subscription_id", params.subscription_id);
  if (params?.case_id) q.set("case_id", params.case_id);
  if (params?.event_type) q.set("event_type", params.event_type);
  const qs = q.toString();
  return request(`/cases/webhooks/deliveries/summary${qs ? `?${qs}` : ""}`);
}

export async function replayCaseWebhookDelivery(deliveryId: string): Promise<CaseWebhookReplayResult> {
  return request(`/cases/webhooks/deliveries/${encodeURIComponent(deliveryId)}/replay`, {
    method: "POST",
  });
}

export async function replayCaseWebhookDlq(params?: {
  subscription_id?: string;
  case_id?: string;
  event_type?: string;
  limit?: number;
}): Promise<CaseWebhookReplayResult> {
  const q = new URLSearchParams();
  if (params?.subscription_id) q.set("subscription_id", params.subscription_id);
  if (params?.case_id) q.set("case_id", params.case_id);
  if (params?.event_type) q.set("event_type", params.event_type);
  if (params?.limit !== undefined) q.set("limit", String(params.limit));
  const qs = q.toString();
  return request(`/cases/webhooks/dlq/replay${qs ? `?${qs}` : ""}`, {
    method: "POST",
  });
}

export async function replayCaseWebhookDlqSelected(deliveryIds: string[]): Promise<CaseWebhookReplayResult> {
  return request("/cases/webhooks/dlq/replay-selected", {
    method: "POST",
    body: JSON.stringify({ delivery_ids: deliveryIds }),
  });
}

export async function purgeCaseWebhookDlq(params?: {
  subscription_id?: string;
  case_id?: string;
  event_type?: string;
  older_than_hours?: number;
  limit?: number;
}): Promise<CaseWebhookPurgeResult> {
  const q = new URLSearchParams();
  if (params?.subscription_id) q.set("subscription_id", params.subscription_id);
  if (params?.case_id) q.set("case_id", params.case_id);
  if (params?.event_type) q.set("event_type", params.event_type);
  if (params?.older_than_hours !== undefined) q.set("older_than_hours", String(params.older_than_hours));
  if (params?.limit !== undefined) q.set("limit", String(params.limit));
  const qs = q.toString();
  return request(`/cases/webhooks/dlq/purge${qs ? `?${qs}` : ""}`, {
    method: "POST",
  });
}

export async function purgeCaseWebhookDlqSelected(
  deliveryIds: string[]
): Promise<CaseWebhookPurgeSelectedResult> {
  return request("/cases/webhooks/dlq/purge-selected", {
    method: "POST",
    body: JSON.stringify({ delivery_ids: deliveryIds }),
  });
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

/* ── Triggers ────────────────────────────── */

export async function listTriggers(): Promise<TriggerRegistration[]> {
  return request("/triggers");
}

export async function getTrigger(
  procedureId: string,
  version: string
): Promise<TriggerRegistration | null> {
  return request(`/triggers/${encodeURIComponent(procedureId)}/${encodeURIComponent(version)}`);
}

export async function upsertTrigger(
  procedureId: string,
  version: string,
  body: {
    trigger_type: string;
    schedule?: string | null;
    webhook_secret?: string | null;
    event_source?: string | null;
    dedupe_window_seconds?: number;
    max_concurrent_runs?: number | null;
    enabled?: boolean;
  }
): Promise<TriggerRegistration> {
  return request(
    `/triggers/${encodeURIComponent(procedureId)}/${encodeURIComponent(version)}`,
    { method: "POST", body: JSON.stringify(body) }
  );
}

export async function deleteTrigger(procedureId: string, version: string): Promise<void> {
  await request(
    `/triggers/${encodeURIComponent(procedureId)}/${encodeURIComponent(version)}`,
    { method: "DELETE" }
  );
}

export async function syncTriggers(): Promise<{ synced: number }> {
  return request("/triggers/sync", { method: "POST" });
}

export async function fireTrigger(
  procedureId: string,
  version: string
): Promise<{ run_id: string; procedure_id: string; procedure_version: string; trigger_type: string }> {
  return request(
    `/triggers/${encodeURIComponent(procedureId)}/${encodeURIComponent(version)}/fire`,
    { method: "POST" }
  );
}

/* ── Auth ───────────────────────────────────────────────────── */

export async function authLogin(username: string, password: string): Promise<{
  access_token: string;
  token_type: string;
  expires_in: number;
  identity: string;
  roles: string[];
}> {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function authMe(): Promise<{
  identity: string;
  roles: string[];
  user_id?: string;
  email?: string;
  full_name?: string;
  role?: string;
}> {
  return request("/auth/me");
}

/* ── Users ──────────────────────────────────────────────────── */

export async function listUsers(): Promise<User[]> {
  return request("/users");
}

export async function createUser(data: {
  username: string;
  email: string;
  password: string;
  full_name?: string;
  role?: string;
}): Promise<User> {
  return request("/users", { method: "POST", body: JSON.stringify(data) });
}

export async function updateUser(
  userId: string,
  data: { full_name?: string; email?: string; role?: string; is_active?: boolean; password?: string }
): Promise<User> {
  return request(`/users/${encodeURIComponent(userId)}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteUser(userId: string): Promise<void> {
  await request(`/users/${encodeURIComponent(userId)}`, { method: "DELETE" });
}

/* ── Secrets ────────────────────────────────────────────────── */

export async function listSecrets(): Promise<Secret[]> {
  return request("/secrets");
}

export async function createSecret(data: {
  name: string;
  value: string;
  description?: string;
  provider_hint?: string;
  tags?: string[];
}): Promise<Secret> {
  return request("/secrets", { method: "POST", body: JSON.stringify(data) });
}

export async function updateSecret(
  name: string,
  data: { value?: string; description?: string; tags?: string[]; provider_hint?: string }
): Promise<Secret> {
  return request(`/secrets/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteSecret(name: string): Promise<void> {
  await request(`/secrets/${encodeURIComponent(name)}`, { method: "DELETE" });
}

/* ── Platform Config ────────────────────────────────────────── */

export async function getConfig(): Promise<import("./types").PlatformConfig> {
  return request("/config");
}

export async function patchConfig(
  data: Partial<import("./types").PlatformConfig>
): Promise<import("./types").PlatformConfig> {
  return request("/config", { method: "PATCH", body: JSON.stringify(data) });
}

export async function testLlmConnection(): Promise<{
  ok: boolean;
  model?: string;
  response?: string;
  error?: string;
}> {
  return request("/config/test-llm", { method: "POST" });
}

/* ── Audit Events ────────────────────────────────────────────── */

export interface AuditEventRecord {
  event_id: number;
  ts: string;
  category: string;
  action: string;
  actor: string;
  description: string;
  resource_type: string | null;
  resource_id: string | null;
  meta: Record<string, unknown> | null;
}

export async function listAuditEvents(params?: {
  category?: string;
  actor?: string;
  action?: string;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<{ events: AuditEventRecord[]; limit: number; offset: number }> {
  const qs = new URLSearchParams();
  if (params?.category) qs.set("category", params.category);
  if (params?.actor) qs.set("actor", params.actor);
  if (params?.action) qs.set("action", params.action);
  if (params?.search) qs.set("search", params.search);
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  if (params?.offset !== undefined) qs.set("offset", String(params.offset));
  const query = qs.toString();
  return request(`/audit${query ? `?${query}` : ""}`);
}

/* ── Health & Workers ────────────────────────────────────────── */

export async function fetchOrchestrators(): Promise<import("./types").OrchestratorWorkerOut[]> {
  return request("/orchestrators");
}

export async function fetchAgentPools(): Promise<import("./types").AgentPoolStats[]> {
  return request("/agents/pools");
}

