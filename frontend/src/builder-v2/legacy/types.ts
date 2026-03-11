import type { BuilderNodeKind } from "@/builder-v2/reference-contract";

export const NODE_TYPES_LIST = [
  "sequence",
  "logic",
  "loop",
  "parallel",
  "human_approval",
  "llm_action",
  "processing",
  "verification",
  "transform",
  "subflow",
  "terminate",
] as const;

export type CkpNodeType = (typeof NODE_TYPES_LIST)[number];

export type NodeCategory = "deterministic" | "intelligent" | "control";

export interface WorkflowTemplate {
  name: string;
  description: string;
  icon: string;
  workflowGraph: Record<string, unknown>;
}

export interface BuilderNodeData {
  label: string;
  nodeType: BuilderNodeKind;
  description: string;
  agent: string;
  isStart: boolean;
  isCheckpoint: boolean;
  status?: string;
  approvalPrompt?: string;
  decisionType?: string;
  timeoutMs?: number;
  llmPrompt?: string;
  llmModel?: string;
  orchestrationMode?: boolean;
  orchestrationBranches?: string;
  loopMaxIterations?: number;
  loopContinueCondition?: string;
  parallelWaitAll?: boolean;
  logicDefaultNext?: string;
  action?: string;
  inputMapping?: string;
  outputMapping?: string;
  transformer?: string;
  verificationRules?: string;
  subflowId?: string;
  subflowVersion?: string;
  onFailureNode?: string;
  retryMaxAttempts?: number;
  retryBackoffMs?: number;
  extraJsonText?: string;
  steps?: Record<string, unknown>[];
  checks?: Record<string, unknown>[];
  outputs?: Record<string, unknown>;
  extra?: Record<string, unknown>;
  [key: string]: unknown;
}