/* TypeScript types matching backend Pydantic schemas */

export interface Procedure {
  procedure_id: string;
  version: string;
  name: string;
  description: string;
  status: string;
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
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
  parent_run_id: string | null;
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
  status: "pending" | "approved" | "rejected" | "timed_out" | "timeout";
  decided_by: string | null;
  decided_at: string | null;
  expires_at: string | null;
  context_data: Record<string, unknown> | null;
  created_at: string;
}

export interface AgentInstance {
  agent_id: string;
  name: string;
  channel: string;
  base_url: string;
  status: "online" | "offline" | "busy";
  resource_key: string;
  concurrency_limit: number;
  capabilities: string[];
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

export interface ResourceLeaseDiagnostic {
  lease_id: string;
  resource_key: string;
  run_id: string;
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
  completed_at: string | null;
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
