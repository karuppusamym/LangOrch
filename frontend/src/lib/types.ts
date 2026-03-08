/* TypeScript types matching backend Pydantic schemas */

/* ── Users ── */
export interface User {
  user_id: string;
  username: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  sso_provider: string | null;
  created_at: string;
  updated_at: string;
}

/* ── Secrets ── */
export interface Secret {
  secret_id: string;
  name: string;
  description: string | null;
  provider_hint: string;
  tags: string[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface Procedure {
  procedure_id: string;
  version: string;
  name: string;
  description: string;
  status: string;
  release_channel: "dev" | "qa" | "prod" | null;
  promoted_from_version: string | null;
  promoted_at: string | null;
  promoted_by: string | null;
  effective_date: string | null;
  project_id: string | null;
  created_at: string;
}

export interface ProcedureDetail extends Procedure {
  ckp_json: Record<string, unknown>;
  provenance: Record<string, unknown> | null;
  retrieval_metadata: Record<string, unknown> | null;
  trigger: Record<string, unknown> | null;
}

export interface ProcedurePromoteResponse {
  promoted: Procedure;
  previous_channel_version: string | null;
}

export interface ProcedureRollbackResponse {
  restored: Procedure;
  replaced_version: string;
}

export interface Run {
  run_id: string;
  procedure_id: string;
  procedure_version: string;
  status: RunStatus;
  thread_id: string;
  input_vars: Record<string, unknown>;
  output_vars: Record<string, unknown> | null;
  total_prompt_tokens: number | null;
  total_completion_tokens: number | null;
  estimated_cost_usd: number | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
  parent_run_id: string | null;
  trigger_type: string | null;
  triggered_by: string | null;
  project_id: string | null;
  case_id: string | null;
  last_node_id: string | null;
  last_step_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  artifact_id: string;
  run_id: string;
  node_id: string | null;
  step_id: string | null;
  kind: string;
  uri: string;
  created_at: string;
}

export type RunStatus =
  | "created"
  | "pending"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "canceled"
  | "cancelled";

export interface RunEvent {
  event_id: string;
  run_id: string;
  event_type: string;
  node_id: string | null;
  step_id: string | null;
  attempt: number | null;
  payload: Record<string, unknown>;
  /** ISO timestamp (backend field name is `ts`) */
  created_at: string;
}

export interface Approval {
  approval_id: string;
  run_id: string;
  node_id: string;
  prompt: string;
  decision_type: string;
  options: string[] | null;
  status: "pending" | "approved" | "rejected" | "timed_out" | "timeout" | "cancelled";
  decided_by: string | null;
  decided_at: string | null;
  expires_at: string | null;
  context_data: Record<string, unknown> | null;
  created_at: string;
  run_status?: string | null;
}

export interface AgentCapability {
  name: string;
  type: string;
  description: string | null;
  estimated_duration_s: number | null;
  is_batch: boolean;
}

export interface AgentInstance {
  agent_id: string;
  name: string;
  channel: string;
  base_url: string;
  status: "online" | "offline" | "busy";
  resource_key: string;
  concurrency_limit: number;
  pool_id: string | null;
  capabilities: AgentCapability[];
  consecutive_failures: number;
  circuit_open_at: string | null;
  updated_at: string;
}

export interface Project {
  project_id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface Case {
  case_id: string;
  project_id: string | null;
  external_ref: string | null;
  case_type: string | null;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  owner: string | null;
  sla_due_at: string | null;
  sla_breached_at: string | null;
  tags: string[] | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface CaseQueueItem extends Case {
  priority_rank: number;
  age_seconds: number;
  sla_remaining_seconds: number | null;
  is_sla_breached: boolean;
}

export interface CaseQueueAnalytics {
  total_active_cases: number;
  unassigned_cases: number;
  breached_cases: number;
  breach_risk_next_window_cases: number;
  breach_risk_next_window_percent: number;
  wait_p50_seconds: number;
  wait_p95_seconds: number;
  wait_by_priority: Record<string, { count: number; wait_p50_seconds: number; wait_p95_seconds: number }>;
  wait_by_case_type: Record<string, { count: number; wait_p50_seconds: number; wait_p95_seconds: number }>;
  reassignment_rate_24h: number;
  abandonment_rate_24h: number;
}

export interface CaseEvent {
  event_id: number;
  case_id: string;
  ts: string;
  event_type: string;
  actor: string | null;
  payload: Record<string, unknown> | null;
}

export interface CaseWebhookSubscription {
  subscription_id: string;
  event_type: string;
  target_url: string;
  project_id: string | null;
  secret_env_var: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface CaseWebhookDelivery {
  delivery_id: string;
  subscription_id: string;
  case_event_id: number | null;
  case_id: string | null;
  project_id: string | null;
  event_type: string;
  status: "pending" | "processing" | "retrying" | "delivered" | "failed";
  attempts: number;
  max_attempts: number;
  next_attempt_at: string;
  last_status_code: number | null;
  last_error: string | null;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseWebhookDeliverySummary {
  total: number;
  by_status: Record<string, number>;
  oldest_pending_age_seconds: number | null;
  recent_failures_last_hour: number;
}

export interface CaseWebhookDeliveryCount {
  total: number;
}

export interface CaseWebhookReplayResult {
  replayed: number;
  delivery_ids: string[];
  skipped_non_failed_ids?: string[];
  not_found_ids?: string[];
}

export interface CaseWebhookPurgeResult {
  deleted: number;
}

export interface CaseWebhookPurgeSelectedResult {
  deleted: number;
  delivery_ids: string[];
  skipped_non_failed_ids?: string[];
  not_found_ids?: string[];
}

export interface CaseSlaPolicy {
  policy_id: string;
  name: string;
  project_id: string | null;
  case_type: string | null;
  priority: string | null;
  due_minutes: number;
  breach_status: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ResourceLeaseDiagnostic {
  lease_id: string;
  resource_key: string;
  run_id?: string;
  node_id: string | null;
  step_id: string | null;
  acquired_at: string;
  expires_at: string;
  released_at: string | null;
  is_active: boolean;
}

export interface StepIdempotencyDiagnostic {
  step_id: string;
  node_id: string;
  idempotency_key: string | null;
  status: string;
  has_cached_result: boolean;
  updated_at: string;
}

export interface RunDiagnostics {
  run_id: string;
  thread_id: string;
  status: string;
  last_node_id: string | null;
  last_step_id: string | null;
  has_retry_event: boolean;
  idempotency_entries: StepIdempotencyDiagnostic[];
  active_leases: ResourceLeaseDiagnostic[];
  total_events: number;
  error_events: number;
}

export interface MetricsSummary {
  counters: Record<string, number | Record<string, number>>;
  histograms?: Record<string, { count: number; sum: number; min: number; max: number; avg: number }>;
  [key: string]: unknown;
}

/* ── Checkpoints ────────────────────────── */

export interface CheckpointMetadata {
  checkpoint_id: string | null;
  thread_id: string;
  parent_checkpoint_id: string | null;
  step: number;
  writes: unknown | null;
  created_at: string;
}

export interface CheckpointState {
  checkpoint_id: string | null;
  thread_id: string;
  channel_values: Record<string, unknown>;
  metadata: Record<string, unknown>;
  pending_writes: unknown[];
  versions_seen: Record<string, unknown>;
}

/* ── Explain (static analysis) ─────────── */

export interface ExplainNode {
  id: string;
  type: string;
  agent: string | null;
  description: string | null;
  is_checkpoint: boolean;
  sla: Record<string, unknown> | null;
  timeout_ms: number | null;
  has_side_effects: boolean;
  steps: { step_id: string; action: string; timeout_ms: number | null; retry_on_failure: boolean; output_variable: string | null; binding_kind: string | null }[];
  error_handlers: { error_type: string; action: string; max_retries: number | null; delay_ms: number | null; fallback_node: string | null }[];
}

export interface ExplainEdge {
  from: string;
  to: string;
  condition: string | null;
}

export interface ExplainVariable {
  name: string;
  required: boolean;
  type: string | null;
  default: unknown;
  provided: boolean;
}

export interface ExplainReport {
  procedure_id: string;
  version: string;
  nodes: ExplainNode[];
  edges: ExplainEdge[];
  variables: {
    schema: Record<string, unknown>;
    required: string[];
    produced: string[];
    missing_inputs: string[];
    provided: string[];
  };
  route_trace: Array<{ node_id: string; type: string; next_nodes: string[]; is_terminal: boolean }>;
  external_calls: { node_id: string; step_id: string | null; action: string; binding_kind: string; binding_ref: string | null; agent_hint: string | null; timeout_ms: number | null }[];
  policy_summary: Record<string, unknown>;
}

/* ── Triggers ─────────────────────────────── */

export interface TriggerRegistration {
  id: number;
  procedure_id: string;
  version: string;
  trigger_type: "scheduled" | "webhook" | "event" | "file_watch" | "manual";
  schedule: string | null;
  webhook_secret: string | null;
  event_source: string | null;
  dedupe_window_seconds: number;
  max_concurrent_runs: number | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
/* ── Platform Config ─────────────────────────────── */

export interface PlatformConfig {
  // Server
  host: string;
  port: number;
  debug: boolean;
  cors_origins: string[];
  // Database
  db_dialect: string;
  db_host: string | null;
  db_port: number | null;
  db_name: string | null;
  db_pool_size: number;
  db_max_overflow: number;
  // Auth
  auth_enabled: boolean;
  auth_token_expire_minutes: number;
  // Worker
  worker_embedded: boolean;
  worker_concurrency: number;
  worker_poll_interval: number;
  worker_max_attempts: number;
  worker_retry_delay_seconds: number;
  worker_lock_duration_seconds: number;
  // LLM
  llm_base_url: string | null;
  llm_timeout_seconds: number;
  llm_key_set: boolean;
  llm_default_model: string;
  llm_gateway_headers: string | null;
  llm_model_cost_json: string | null;
  llm_api_key?: string;
  // Apigee
  apigee_enabled: boolean;
  apigee_token_url: string | null;
  apigee_certs_path: string | null;
  apigee_consumer_key: string | null;
  apigee_client_secret: string | null;
  apigee_use_case_id: string | null;
  apigee_client_id: string | null;
  // Retention
  checkpoint_retention_days: number;
  artifact_retention_days: number;
  // Leases / metrics
  lease_ttl_seconds: number;
  metrics_push_url: string | null;
  metrics_push_interval_seconds: number;
  metrics_push_job: string;
  // Alerts & limits
  alert_webhook_url: string | null;
  rate_limit_max_concurrent: number;
  secrets_rotation_check: boolean;
}

export interface OrchestratorWorkerOut {
  worker_id: string;
  status: string;
  is_leader: boolean;
  last_heartbeat_at: string;
}

export interface AgentPoolStats {
  pool_id: string;
  channel: string;
  agent_count: number;
  status_breakdown: Record<string, number>;
  concurrency_limit_total: number;
  active_leases: number;
  available_capacity: number;
  circuit_open_count: number;
}
