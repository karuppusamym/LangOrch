/* TypeScript types matching backend Pydantic schemas */

export interface Project {
  project_id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface Procedure {
  procedure_id: string;
  version: string;
  name: string;
  description: string;
  project_id: string | null;
  created_at: string;
}

export interface ProcedureDetail extends Procedure {
  ckp_json: Record<string, unknown>;
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
}

export interface ActionCatalog {
  [channel: string]: string[];
}
