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
}

export interface Run {
  run_id: string;
  procedure_id: string;
  procedure_version: string;
  status: RunStatus;
  thread_id: string;
  input_vars: Record<string, unknown>;
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
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Approval {
  approval_id: string;
  run_id: string;
  node_id: string;
  prompt: string;
  status: "pending" | "approved" | "rejected" | "timed_out";
  decided_by: string | null;
  decided_at: string | null;
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
  status: string;
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
  [key: string]: unknown;
}
