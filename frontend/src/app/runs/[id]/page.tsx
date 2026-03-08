"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { getRun, listRunEvents, listRunArtifacts, cancelRun, retryRun, createRun, getRunDiagnostics, getGraph, listRunCheckpoints, getCheckpointState, getProcedure, listApprovals, submitApprovalDecision, isNotFoundError } from "@/lib/api";
import { subscribeToRunEvents } from "@/lib/sse";
import { useToast } from "@/components/Toast";
import { redactInputVars, isFieldSensitive, REDACTION_PLACEHOLDER, flattenVariablesSchema } from "@/lib/redact";
import type { Run, RunEvent, Artifact, RunDiagnostics, CheckpointMetadata, CheckpointState, ProcedureDetail, Approval } from "@/lib/types";

const WorkflowGraph = dynamic(
  () => import("@/components/WorkflowGraphWrapper"),
  { ssr: false, loading: () => <p className="text-sm text-gray-400">Loading graph…</p> },
);

/* ── helpers ─────────────────────────────────────────────────── */

/** Human-readable label for event types */
const EVENT_LABELS: Record<string, string> = {
  run_created: "Run Created",
  run_completed: "Run Completed",
  run_failed: "Run Failed",
  run_canceled: "Run Canceled",
  run_cancelled: "Run Cancelled",
  run_retry_requested: "Retry Requested",
  execution_started: "Execution Started",
  execution_resumed: "Execution Resumed",
  node_started: "Node Started",
  node_completed: "Node Completed",
  node_paused: "Node Paused",
  node_error: "Node Error",
  step_started: "Step Started",
  step_completed: "Step Completed",
  step_error_notification: "Step Error",
  step_timeout: "Step Timeout",
  dry_run_step_skipped: "Step Skipped (Dry Run)",
  approval_requested: "Approval Requested",
  approval_decided: "Approval Decided",
  approval_decision_received: "Approval Decision Received",
  approval_decide_received: "Approval Decision Received",
  approval_expired: "Approval Expired",
  llm_usage: "LLM Usage",
  artifact_created: "Artifact Created",
  checkpoint_saved: "Checkpoint Saved",
  sla_breached: "SLA Breached",
  loop_iteration: "Loop Iteration",
  error: "Error",
};

function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Extract a short human-readable message from an event payload */
function extractErrorMessage(payload: Record<string, unknown> | null | undefined): string | null {
  if (!payload) return null;
  const msg =
    (payload.message as string | undefined) ??
    (payload.error as string | undefined) ??
    (payload.detail as string | undefined) ??
    (payload.reason as string | undefined) ??
    (payload.exception as string | undefined);
  return msg ?? null;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

async function copyText(text: string, toast: (msg: string, type: "success") => void) {
  try { await navigator.clipboard.writeText(text); toast("Copied", "success"); } catch { /* ignore */ }
}

interface NodeStatus {
  state: "running" | "completed" | "failed" | "sla_breached" | "current" | "pending" | "paused";
  loopCount?: string;
}

function buildNodeStateMap(
  events: RunEvent[],
  currentNodeId: string | null,
  runStatus: Run["status"]
): Record<string, NodeStatus> {
  const map: Record<string, NodeStatus> = {};
  const loopIterationsByNode: Record<string, number> = {};

  for (const ev of events) {
    if (!ev.node_id) continue;

    const nodeId = ev.node_id;
    const prior = map[nodeId]?.state;

    // 1. Error states — highest priority, sticky once set
    if (["node_error", "step_error_notification", "step_timeout"].includes(ev.event_type)) {
      map[nodeId] = { ...(map[nodeId] ?? {}), state: "failed" };
      continue;
    }

    // 2. SLA breach — sticky unless already failed
    if (ev.event_type === "sla_breached") {
      if (prior !== "failed") {
        map[nodeId] = { ...(map[nodeId] ?? {}), state: "sla_breached" };
      }
      continue;
    }

    // 3. Completion — node_completed or step_completed both indicate the
    //    node (or its last step) finished.  Can be overridden by a later
    //    step_started for multi-step nodes.
    if (["node_completed", "step_completed"].includes(ev.event_type)) {
      if (prior !== "failed" && prior !== "sla_breached") {
        map[nodeId] = { ...(map[nodeId] ?? {}), state: "completed" };
      }
      continue;
    }

    // 3b. Paused — approval node waiting for human decision
    if (ev.event_type === "node_paused" || ev.event_type === "approval_requested") {
      if (prior !== "failed" && prior !== "sla_breached") {
        map[nodeId] = { ...(map[nodeId] ?? {}), state: "paused" };
      }
      continue;
    }

    // 4. Start events — set to running; overrides "completed" for multi-step nodes
    if (["node_started", "step_started"].includes(ev.event_type)) {
      if (prior !== "failed" && prior !== "sla_breached" && prior !== "paused") {
        map[nodeId] = { ...(map[nodeId] ?? {}), state: "running" };
      }
      continue;
    }

    // 5. Loop iteration tracking
    if (ev.event_type === "loop_iteration") {
      const payload = (ev.payload as Record<string, unknown> | null) ?? {};
      const total = payload.total !== undefined ? Number(payload.total) : undefined;
      const iteration = payload.iteration !== undefined ? Number(payload.iteration) + 1 : undefined;

      if (iteration !== undefined && Number.isFinite(iteration)) {
        loopIterationsByNode[nodeId] = Math.max(loopIterationsByNode[nodeId] ?? 0, iteration);
      } else {
        loopIterationsByNode[nodeId] = (loopIterationsByNode[nodeId] ?? 0) + 1;
      }

      const loopCount = total && Number.isFinite(total)
        ? `${loopIterationsByNode[nodeId]}/${total}`
        : `${loopIterationsByNode[nodeId]}`;

      map[nodeId] = { ...(map[nodeId] ?? { state: "running" }), loopCount };
    }
  }

  // Override based on run terminal status + currentNodeId
  if (currentNodeId) {
    if (runStatus === "failed") {
      map[currentNodeId] = { ...(map[currentNodeId] ?? {}), state: "failed" };
    } else if (runStatus === "completed") {
      map[currentNodeId] = { ...(map[currentNodeId] ?? {}), state: "completed" };
    } else if (runStatus === "waiting_approval" && map[currentNodeId]?.state !== "failed") {
      // Approval node is paused — show amber "waiting" state
      map[currentNodeId] = { ...(map[currentNodeId] ?? {}), state: "paused" };
    } else if (["running", "created"].includes(runStatus) && map[currentNodeId]?.state !== "failed") {
      map[currentNodeId] = { ...(map[currentNodeId] ?? {}), state: "current" };
    }
  }

  // If run is still active, mark the most-recently-started node as "current"
  if (["running", "created"].includes(runStatus)) {
    const lastStarted = [...events]
      .reverse()
      .find((ev) => ev.node_id && ["node_started", "step_started"].includes(ev.event_type));
    if (lastStarted?.node_id && map[lastStarted.node_id]?.state === "running") {
      map[lastStarted.node_id] = { ...map[lastStarted.node_id], state: "current" };
    }
  }

  return map;
}

function buildEdgeTraversalCounts(events: RunEvent[]): Record<string, number> {
  const counts: Record<string, number> = {};
  const started = events
    .filter((ev) => ev.event_type === "node_started" && !!ev.node_id)
    .sort((a, b) => {
      const at = new Date(a.created_at).getTime();
      const bt = new Date(b.created_at).getTime();
      if (at !== bt) return at - bt;
      return String(a.event_id).localeCompare(String(b.event_id));
    });

  for (let i = 1; i < started.length; i += 1) {
    const from = started[i - 1].node_id;
    const to = started[i].node_id;
    if (!from || !to) continue;
    const key = `${from}=>${to}`;
    counts[key] = (counts[key] ?? 0) + 1;
  }

  return counts;
}

interface StepExecutionSummary {
  stepId: string;
  action: string | null;
  status: "running" | "completed" | "failed" | "timeout" | "cached";
  startedAt: string | null;
  completedAt: string | null;
  durationMs: number | null;
  retryCount: number;
  error: string | null;
}

interface NodeExecutionSummary {
  nodeId: string;
  nodeName: string | null;
  status: NodeStatus["state"];
  startedAt: string | null;
  finishedAt: string | null;
  lastUpdatedAt: string | null;
  approvalId: string | null;
  pauseReason: string | null;
  error: string | null;
  steps: StepExecutionSummary[];
}

function buildNodeExecutionSummaries(
  events: RunEvent[],
  nodeStateMap: Record<string, NodeStatus>
): NodeExecutionSummary[] {
  const nodes = new Map<string, NodeExecutionSummary>();
  const stepsByNode = new Map<string, Map<string, StepExecutionSummary>>();
  const sortedEvents = [...events].sort((left, right) => {
    const leftTime = new Date(left.created_at).getTime();
    const rightTime = new Date(right.created_at).getTime();
    if (leftTime !== rightTime) return leftTime - rightTime;
    return Number(left.event_id) - Number(right.event_id);
  });

  for (const event of sortedEvents) {
    if (!event.node_id) continue;
    const payload = event.payload ?? {};
    const nodeId = event.node_id;
    const existing = nodes.get(nodeId) ?? {
      nodeId,
      nodeName: null,
      status: "pending" as NodeStatus["state"],
      startedAt: null,
      finishedAt: null,
      lastUpdatedAt: null,
      approvalId: null,
      pauseReason: null,
      error: null,
      steps: [],
    };
    existing.lastUpdatedAt = event.created_at;
    if (typeof payload.node_name === "string" && payload.node_name.trim()) {
      existing.nodeName = payload.node_name;
    }

    const stepCollection = stepsByNode.get(nodeId) ?? new Map<string, StepExecutionSummary>();
    stepsByNode.set(nodeId, stepCollection);

    const getStep = (stepId: string): StepExecutionSummary => {
      const cached = stepCollection.get(stepId) ?? {
        stepId,
        action: null,
        status: "running",
        startedAt: null,
        completedAt: null,
        durationMs: null,
        retryCount: 0,
        error: null,
      };
      stepCollection.set(stepId, cached);
      return cached;
    };

    switch (event.event_type) {
      case "node_started":
        existing.startedAt ??= event.created_at;
        existing.status = "running";
        break;
      case "node_completed":
        existing.finishedAt = event.created_at;
        existing.status = "completed";
        break;
      case "node_paused":
        existing.finishedAt = event.created_at;
        existing.status = "paused";
        existing.pauseReason = typeof payload.reason === "string" ? payload.reason : existing.pauseReason;
        break;
      case "approval_requested":
        existing.status = "paused";
        existing.approvalId = typeof payload.approval_id === "string" ? payload.approval_id : existing.approvalId;
        break;
      case "node_error":
        existing.finishedAt = event.created_at;
        existing.status = "failed";
        existing.error = extractErrorMessage(payload) ?? existing.error;
        break;
      case "sla_breached":
        if (existing.status !== "failed") {
          existing.status = "sla_breached";
        }
        break;
      case "step_started": {
        if (!event.step_id) break;
        const step = getStep(event.step_id);
        step.startedAt ??= event.created_at;
        step.status = "running";
        step.action = typeof payload.action === "string" ? payload.action : step.action;
        break;
      }
      case "step_completed": {
        if (!event.step_id) break;
        const step = getStep(event.step_id);
        step.completedAt = event.created_at;
        step.action = typeof payload.action === "string" ? payload.action : step.action;
        step.status = payload.cached ? "cached" : "completed";
        step.durationMs = typeof payload.duration_ms === "number" ? Number(payload.duration_ms) : step.durationMs;
        step.retryCount = typeof payload.retry_count === "number" ? Number(payload.retry_count) : step.retryCount;
        break;
      }
      case "step_timeout": {
        if (!event.step_id) break;
        const step = getStep(event.step_id);
        step.completedAt = event.created_at;
        step.status = "timeout";
        step.error = extractErrorMessage(payload) ?? "Step timed out";
        break;
      }
      case "step_error_notification": {
        if (!event.step_id) break;
        const step = getStep(event.step_id);
        step.completedAt = event.created_at;
        step.status = "failed";
        step.error = extractErrorMessage(payload) ?? "Step failed";
        step.action = typeof payload.action === "string" ? payload.action : step.action;
        existing.error = step.error;
        break;
      }
      default:
        break;
    }

    existing.steps = Array.from(stepCollection.values());
    const override = nodeStateMap[nodeId]?.state;
    if (override) {
      existing.status = override;
    }
    nodes.set(nodeId, existing);
  }

  return Array.from(nodes.values()).sort((left, right) => {
    const leftTime = new Date(left.startedAt ?? left.lastUpdatedAt ?? 0).getTime();
    const rightTime = new Date(right.startedAt ?? right.lastUpdatedAt ?? 0).getTime();
    return leftTime - rightTime;
  });
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function formatMilliseconds(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  if (value < 1000) return `${Math.round(value)}ms`;
  return `${(value / 1000).toFixed(1)}s`;
}

function getEventHighlights(event: RunEvent): string[] {
  const payload = event.payload ?? {};
  const highlights: string[] = [];
  const push = (value: unknown) => {
    if (typeof value === "string" && value.trim()) highlights.push(value.trim());
  };

  switch (event.event_type) {
    case "step_started":
      if (typeof payload.action === "string") highlights.push(`action ${payload.action}`);
      break;
    case "step_completed":
      if (typeof payload.action === "string") highlights.push(`action ${payload.action}`);
      if (payload.cached) highlights.push("cached result reused");
      if (typeof payload.duration_ms === "number") highlights.push(`duration ${formatMilliseconds(Number(payload.duration_ms))}`);
      if (typeof payload.retry_count === "number" && Number(payload.retry_count) > 0) highlights.push(`retries ${Number(payload.retry_count)}`);
      if (typeof payload.output_variable === "string" && payload.output_variable) highlights.push(`stored in ${payload.output_variable}`);
      break;
    case "step_timeout":
      if (typeof payload.timeout_ms === "number") highlights.push(`timeout ${formatMilliseconds(Number(payload.timeout_ms))}`);
      push(extractErrorMessage(payload));
      break;
    case "step_error_notification":
      if (typeof payload.handler_action === "string") highlights.push(`handler ${payload.handler_action}`);
      push(extractErrorMessage(payload));
      break;
    case "node_paused":
      if (typeof payload.reason === "string") highlights.push(`reason ${payload.reason}`);
      break;
    case "approval_requested":
      if (typeof payload.approval_id === "string") highlights.push(`approval ${payload.approval_id.slice(0, 12)}...`);
      break;
    case "approval_decision_received":
    case "approval_decide_received":
      if (typeof payload.decision === "string") highlights.push(`decision ${payload.decision}`);
      if (typeof payload.decided_by === "string") highlights.push(`by ${payload.decided_by}`);
      if (typeof payload.comment === "string" && payload.comment.trim()) highlights.push(payload.comment.trim());
      break;
    case "loop_iteration":
      if (typeof payload.iteration === "number" && typeof payload.total === "number") {
        highlights.push(`iteration ${Number(payload.iteration) + 1}/${Number(payload.total)}`);
      }
      break;
    case "artifact_created":
      if (typeof payload.kind === "string") highlights.push(`artifact ${payload.kind}`);
      if (typeof payload.uri === "string") highlights.push(payload.uri);
      break;
    case "node_error":
    case "run_failed":
      push(extractErrorMessage(payload));
      break;
    case "sla_breached":
      if (typeof payload.actual_duration_ms === "number") highlights.push(`actual ${formatMilliseconds(Number(payload.actual_duration_ms))}`);
      if (typeof payload.max_duration_ms === "number") highlights.push(`limit ${formatMilliseconds(Number(payload.max_duration_ms))}`);
      if (typeof payload.elapsed_ms === "number") highlights.push(`elapsed ${formatMilliseconds(Number(payload.elapsed_ms))}`);
      if (typeof payload.limit_ms === "number") highlights.push(`limit ${formatMilliseconds(Number(payload.limit_ms))}`);
      break;
    case "llm_usage":
      if (typeof payload.model === "string") highlights.push(`model ${payload.model}`);
      if (typeof payload.total_tokens === "number") highlights.push(`tokens ${payload.total_tokens}`);
      break;
    default:
      break;
  }

  return highlights;
}

type TimelineFilter = "all" | "errors" | "steps" | "nodes";

/* ── component ───────────────────────────────────────────────── */


export default function RunDetailPage() {
  const params = useParams();
  const runId = params.id as string;
  const { toast } = useToast();

  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [diagnostics, setDiagnostics] = useState<RunDiagnostics | null>(null);
  const [graphData, setGraphData] = useState<{ nodes: unknown[]; edges: unknown[] } | null>(null);
  const [checkpoints, setCheckpoints] = useState<CheckpointMetadata[]>([]);
  const [selectedCkpt, setSelectedCkpt] = useState<CheckpointState | null>(null);
  const [loadingCkpt, setLoadingCkpt] = useState(false);
  const [artifactNotice, setArtifactNotice] = useState(false);
  const [loading, setLoading] = useState(true);
  const [liveMode, setLiveMode] = useState(true);
  const [activeTab, setActiveTab] = useState<"timeline" | "graph" | "artifacts" | "diagnostics" | "checkpoints">("timeline");
  const [timelineFilter, setTimelineFilter] = useState<TimelineFilter>("all");
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set());
  // Pending approval for this run (populated when run.status === 'waiting_approval')
  const [pendingApproval, setPendingApproval] = useState<Approval | null>(null);
  const [approvalDeciding, setApprovalDeciding] = useState(false);
  const [approverName, setApproverName] = useState(() =>
    typeof window !== "undefined" ? (localStorage.getItem("approver_name") ?? "") : ""
  );
  const timelineRef = useRef<HTMLDivElement>(null);

  // Retry-with-modified-inputs modal state
  const [showRetryModal, setShowRetryModal] = useState(false);
  const [retryVarsForm, setRetryVarsForm] = useState<Record<string, string>>({});
  const [retryVarsErrors, setRetryVarsErrors] = useState<Record<string, string>>({});
  const [retryCreating, setRetryCreating] = useState(false);
  const [procedureDetail, setProcedureDetail] = useState<ProcedureDetail | null>(null);
  const [procedureLoadIssue, setProcedureLoadIssue] = useState<string | null>(null);

  // Load run + events
  useEffect(() => {
    async function load() {
      try {
        setProcedureLoadIssue(null);
        const [r, evts, arts] = await Promise.all([
          getRun(runId),
          listRunEvents(runId),
          listRunArtifacts(runId),
        ]);
        setRun(r);
        setEvents(evts);
        setArtifacts(arts);
        getRunDiagnostics(runId).then(setDiagnostics).catch(() => null);
        listRunCheckpoints(runId).then(setCheckpoints).catch(() => null);
        // Load procedure detail for schema-based sensitive-field detection.
        // Only request graph if the procedure version exists.
        getProcedure(r.procedure_id, r.procedure_version)
          .then((detail) => {
            setProcedureDetail(detail);
            return getGraph(r.procedure_id, r.procedure_version)
              .then((d) => setGraphData(d as { nodes: unknown[]; edges: unknown[] }))
              .catch((err) => {
                if (isNotFoundError(err)) {
                  setGraphData(null);
                  setProcedureLoadIssue("Referenced procedure graph is no longer available.");
                }
                return null;
              });
          })
          .catch((err) => {
            if (isNotFoundError(err)) {
              setProcedureDetail(null);
              setGraphData(null);
              setProcedureLoadIssue("Referenced procedure version is no longer available.");
              return null;
            }
            return null;
          });
        // Load pending approval if run is waiting
        if (r.status === "waiting_approval") {
          listApprovals()
            .then((all) => {
              const pa = all.find((a) => a.run_id === runId && a.status === "pending") ?? null;
              setPendingApproval(pa);
            })
            .catch(() => null);
        }
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [runId]);

  // SSE subscription for live events
  useEffect(() => {
    if (!liveMode) return;
    const cleanup = subscribeToRunEvents(runId, (event) => {
      setEvents((prev) => {
        if (prev.some((e) => e.event_id === event.event_id)) return prev;
        return [...prev, event];
      });
      if (event.event_type === "artifact_created") {
        setArtifactNotice(true);
        window.setTimeout(() => setArtifactNotice(false), 2500);
        void listRunArtifacts(runId)
          .then((arts) => setArtifacts(arts))
          .catch((err) => console.error("Failed to refresh artifacts", err));
      }
      // Refresh run row on status-changing events to pick up latest status, error_message, etc.
      if ([
        "run_completed", "run_failed", "run_canceled", "run_cancelled",
        "approval_requested", "approval_decided", "approval_decision_received",
        "approval_decide_received", "execution_resumed",
      ].includes(event.event_type)) {
        getRun(runId).then((r) => {
          setRun(r);
          // Refresh pending approval when run transitions to/from waiting_approval
          if (r.status === "waiting_approval") {
            listApprovals()
              .then((all) => {
                const pa = all.find((a) => a.run_id === runId && a.status === "pending") ?? null;
                setPendingApproval(pa);
              })
              .catch(() => null);
          } else {
            setPendingApproval(null);
          }
        }).catch(console.error);
      }
    });
    return cleanup;
  }, [runId, liveMode]);

  // Auto-scroll timeline
  useEffect(() => {
    if (timelineRef.current) {
      timelineRef.current.scrollTop = timelineRef.current.scrollHeight;
    }
  }, [events]);

  async function handleCancel() {
    if (!run) return;
    try {
      await cancelRun(run.run_id);
      setRun({ ...run, status: "cancelled" });
      toast("Run cancelled", "info");
    } catch {
      toast("Failed to cancel run", "error");
    }
  }

  async function handleRetry() {
    if (!run) return;
    // Fetch procedure detail to get variables_schema
    try {
      const proc = await getProcedure(run.procedure_id, run.procedure_version);
      setProcedureDetail(proc);
      const schema = flattenVariablesSchema((proc.ckp_json as any)?.variables_schema ?? {});
      const schemaEntries = Object.entries(schema) as [string, any][];
      const defaults: Record<string, string> = {};
      // Pre-fill with original run input_vars, falling back to schema defaults
      schemaEntries.forEach(([k, v]) => {
        const original = run.input_vars?.[k];
        if (original !== undefined) {
          defaults[k] = typeof original === "object" ? JSON.stringify(original) : String(original);
        } else {
          defaults[k] = v?.default !== undefined ? String(v.default) : "";
        }
      });
      // Also include any extra vars from the original run not in schema
      if (run.input_vars) {
        for (const [k, v] of Object.entries(run.input_vars)) {
          if (!(k in defaults)) {
            defaults[k] = typeof v === "object" ? JSON.stringify(v) : String(v);
          }
        }
      }
      setRetryVarsForm(defaults);
      setRetryVarsErrors({});
      setShowRetryModal(true);
    } catch (err) {
      if (isNotFoundError(err)) {
        toast("Referenced procedure version is no longer available. Retrying without schema.", "warning");
        // Fallback: allow direct retry without schema
        try {
          const newRun = await retryRun(run.run_id);
          toast("Run retried", "success");
          window.location.href = `/runs/${newRun.run_id}`;
        } catch {
          toast("Failed to retry run", "error");
        }
        return;
      }
      // Fallback: cannot load procedure, do simple retry
      try {
        const newRun = await retryRun(run.run_id);
        toast("Retry run created", "success");
        window.location.href = `/runs/${newRun.run_id}`;
      } catch {
        toast("Failed to retry run", "error");
      }
    }
  }

  function validateRetryField(key: string, raw: string, meta: Record<string, any>): string {
    const validation = (meta?.validation ?? {}) as Record<string, any>;
    const vtype = (meta?.type ?? "string") as string;
    if (meta?.required && !raw.trim()) return "This field is required";
    if (!raw) return "";
    if (validation.regex) {
      try {
        if (!new RegExp(`^(?:${validation.regex as string})$`).test(raw))
          return `Must match pattern: ${validation.regex as string}`;
      } catch { /* invalid regex — skip */ }
    }
    if (vtype === "number") {
      const num = Number(raw);
      if (validation.min !== undefined && num < (validation.min as number))
        return `Minimum value is ${validation.min as number}`;
      if (validation.max !== undefined && num > (validation.max as number))
        return `Maximum value is ${validation.max as number}`;
    }
    const allowed = validation.allowed_values as string[] | undefined;
    if (allowed && !allowed.includes(raw)) return `Must be one of: ${allowed.join(", ")}`;
    return "";
  }

  function handleRetryVarChange(key: string, raw: string, meta: Record<string, any>) {
    setRetryVarsForm((prev) => ({ ...prev, [key]: raw }));
    const err = validateRetryField(key, raw, meta);
    setRetryVarsErrors((prev) => {
      const next = { ...prev };
      if (err) next[key] = err;
      else delete next[key];
      return next;
    });
  }

  async function doRetryRun(vars: Record<string, unknown>) {
    if (!run) return;
    setRetryCreating(true);
    try {
      const newRun = await createRun(
        run.procedure_id,
        run.procedure_version,
        vars,
        { case_id: run.case_id ?? undefined, project_id: run.project_id ?? undefined }
      );
      toast("Retry run created with modified inputs", "success");
      window.location.href = `/runs/${newRun.run_id}`;
    } catch {
      toast("Failed to create retry run", "error");
      setRetryCreating(false);
    }
  }

  async function handleApprovalDecision(decision: "approved" | "rejected") {
    if (!pendingApproval) return;
    setApprovalDeciding(true);
    try {
      await submitApprovalDecision(
        pendingApproval.approval_id,
        decision,
        approverName.trim() || "ui_user"
      );
      toast(`Approval ${decision}`, "success");
      setPendingApproval(null);
    } catch {
      toast("Failed to submit decision", "error");
    } finally {
      setApprovalDeciding(false);
    }
  }

  if (loading) return <p className="text-gray-500">Loading run…</p>;
  if (!run) return <p className="text-red-500">Run not found</p>;

  const isError = (t: string) =>
    ["error", "run_failed", "node_error", "step_timeout", "sla_breached", "step_error_notification"].includes(t);
  const errorCount = events.filter((e) => isError(e.event_type)).length;
  const filteredEvents = events.filter((e) => {
    if (timelineFilter === "errors") return isError(e.event_type);
    if (timelineFilter === "steps") return e.event_type.startsWith("step_");
    if (timelineFilter === "nodes") return e.event_type.startsWith("node_");
    return true;
  });
  const nodeStateMap = buildNodeStateMap(events, run.last_node_id ?? null, run.status);
  const edgeTraversalCounts = buildEdgeTraversalCounts(events);
  const nodeSummaries = buildNodeExecutionSummaries(events, nodeStateMap);
  const completedSteps = nodeSummaries.reduce((sum, node) => sum + node.steps.filter((step) => step.status === "completed" || step.status === "cached").length, 0);
  const failedSteps = nodeSummaries.reduce((sum, node) => sum + node.steps.filter((step) => step.status === "failed" || step.status === "timeout").length, 0);
  const pausedNodes = nodeSummaries.filter((node) => node.status === "paused").length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link href="/runs" className="text-sm text-primary-600 hover:underline">← Runs</Link>
          <div className="mt-2 flex items-center gap-3">
            <h2 className="text-xl font-bold text-gray-900 font-mono">
              {run.run_id.slice(0, 12)}…
            </h2>
            <button title="Copy run ID" onClick={() => void copyText(run.run_id, toast)} className="text-gray-400 hover:text-gray-700">
              <ClipboardIcon />
            </button>
            <RunStatusBadge status={run.status} />
          </div>
          <p className="mt-1 text-sm text-gray-500">
            Procedure:{" "}
            <Link
              href={`/procedures/${encodeURIComponent(run.procedure_id)}/${encodeURIComponent(run.procedure_version)}`}
              className="text-primary-600 hover:underline"
            >
              {run.procedure_id} v{run.procedure_version}
            </Link>
          </p>
        </div>
        <div className="flex gap-2">
          {(["running", "created", "waiting_approval"].includes(run.status)) && (
            <button onClick={handleCancel} className="rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50">Cancel</button>
          )}
          {run.status === "failed" && (
            <button onClick={handleRetry} className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700">Retry</button>
          )}
        </div>
      </div>

      {/* Approval action banner */}
      {run.status === "waiting_approval" && pendingApproval && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 dark:bg-amber-950/20 p-4 space-y-3">
          <div className="flex items-start gap-3">
            <span className="text-2xl">✋</span>
            <div className="flex-1">
              <p className="font-semibold text-amber-800 dark:text-amber-300">Awaiting Approval</p>
              <p className="text-sm text-amber-700 dark:text-amber-400 mt-1">{pendingApproval.prompt}</p>
              <p className="text-xs text-amber-600 dark:text-amber-500 mt-1">Node: {pendingApproval.node_id}</p>
              <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-amber-700 dark:text-amber-300">
                {pendingApproval.expires_at && <span className="rounded-full bg-amber-100 px-2 py-0.5 dark:bg-amber-900/40">Due {formatTimestamp(pendingApproval.expires_at)}</span>}
                {pendingApproval.options?.length ? <span className="rounded-full bg-amber-100 px-2 py-0.5 dark:bg-amber-900/40">Options: {pendingApproval.options.join(", ")}</span> : null}
                {pendingApproval.context_data ? <span className="rounded-full bg-amber-100 px-2 py-0.5 dark:bg-amber-900/40">Context fields: {Object.keys(pendingApproval.context_data).length}</span> : null}
              </div>
            </div>
            <Link href="/approvals" className="text-xs text-amber-600 hover:underline whitespace-nowrap">View all approvals →</Link>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <input
              value={approverName}
              onChange={(e) => {
                setApproverName(e.target.value);
                localStorage.setItem("approver_name", e.target.value);
              }}
              placeholder="Your name (optional)"
              className="rounded-lg border border-amber-300 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm w-44"
            />
            <button
              disabled={approvalDeciding}
              onClick={() => void handleApprovalDecision("approved")}
              className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              ✓ Approve
            </button>
            <button
              disabled={approvalDeciding}
              onClick={() => void handleApprovalDecision("rejected")}
              className="rounded-lg bg-red-500 px-4 py-2 text-sm font-medium text-white hover:bg-red-600 disabled:opacity-50"
            >
              ✕ Reject
            </button>
          </div>
        </div>
      )}

      {/* Error banner */}
      {run.status === "failed" && run.error_message && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4">
          <p className="mb-1 text-sm font-semibold text-red-700">Failure reason</p>
          <pre className="whitespace-pre-wrap break-words font-mono text-xs text-red-600">{run.error_message}</pre>
        </div>
      )}

      {/* Procedure reference warning */}
      {procedureLoadIssue && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm font-semibold text-amber-800">Procedure Version Unavailable</p>
          <p className="mt-1 text-sm text-amber-700">
            {procedureLoadIssue} Historical run data is still available.
          </p>
        </div>
      )}

      {/* Metric cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <InfoCard label="Thread ID" value={run.thread_id.slice(0, 12) + "…"} onCopy={() => void copyText(run.thread_id, toast)} />
        <InfoCard label="Created" value={new Date(run.created_at).toLocaleString()} />
        {run.started_at
          ? <InfoCard label="Started" value={new Date(run.started_at).toLocaleString()} />
          : <InfoCard label="Updated" value={new Date(run.updated_at).toLocaleString()} />}
        {run.duration_seconds != null
          ? <InfoCard label="Duration" value={formatDuration(run.duration_seconds)} />
          : run.ended_at
            ? <InfoCard label="Ended" value={new Date(run.ended_at).toLocaleString()} />
            : <InfoCard label="Last Node" value={run.last_node_id ?? "—"} />}
      </div>

      {/* LLM token usage */}
      {(run.total_prompt_tokens != null || run.total_completion_tokens != null) && (
        <div className="flex flex-wrap items-center gap-4 rounded-xl border border-blue-100 bg-blue-50 px-4 py-2.5 text-xs text-blue-800">
          <span className="font-semibold">LLM tokens this run:</span>
          <span>Prompt: <strong>{run.total_prompt_tokens ?? 0}</strong></span>
          <span>Completion: <strong>{run.total_completion_tokens ?? 0}</strong></span>
          <span>Total: <strong>{(run.total_prompt_tokens ?? 0) + (run.total_completion_tokens ?? 0)}</strong></span>
          {run.estimated_cost_usd != null && (
            <span>Cost: <strong>${run.estimated_cost_usd.toFixed(6)}</strong></span>
          )}
        </div>
      )}

      {/* Input variables — filter out __ system-internal keys before displaying */}
      {run.input_vars && Object.keys(run.input_vars).filter(k => !k.startsWith('__')).length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900">Input Variables</h3>
            <span className="text-[10px] text-gray-400">(sensitive fields redacted)</span>
          </div>
          <pre className="rounded-lg bg-gray-50 p-3 font-mono text-xs">
            {JSON.stringify(
              redactInputVars(
                Object.fromEntries(Object.entries(run.input_vars).filter(([k]) => !k.startsWith('__'))),
                flattenVariablesSchema((procedureDetail?.ckp_json as any)?.variables_schema ?? {})
              ),
              null,
              2
            )}
          </pre>
        </div>
      )}

      {/* Tabs */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex border-b border-gray-200">
          {(["timeline", "graph", "artifacts", "checkpoints", "diagnostics"] as const).map((tab) => (
            <button key={tab} onClick={() => setActiveTab(tab)} className={`px-5 py-3 text-sm font-medium capitalize transition ${activeTab === tab ? "border-b-2 border-primary-600 text-primary-600" : "text-gray-500 hover:text-gray-700"}`}>
              {tab === "artifacts" ? `Artifacts (${artifacts.length})`
                : tab === "timeline" ? `Timeline (${events.length}${errorCount ? ` · ${errorCount} err` : ""})`
                  : tab === "graph" ? "Live Graph"
                    : tab === "checkpoints" ? `Checkpoints (${checkpoints.length})`
                      : "Diagnostics"}
            </button>
          ))}
        </div>

        <div className="p-6">
          {/* Timeline */}
          {activeTab === "timeline" && (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {(["all", "errors", "steps", "nodes"] as TimelineFilter[]).map((f) => (
                  <button key={f} onClick={() => setTimelineFilter(f)} className={`rounded-full px-3 py-1 text-xs font-medium transition ${timelineFilter === f ? "bg-primary-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}>
                    {f === "all" ? `All (${events.length})` : f === "errors" ? `Errors (${errorCount})` : f.charAt(0).toUpperCase() + f.slice(1)}
                  </button>
                ))}
                <label className="ml-auto flex items-center gap-2 text-sm text-gray-500">
                  <input type="checkbox" checked={liveMode} onChange={(e) => setLiveMode(e.target.checked)} className="rounded" />
                  Live
                </label>
              </div>
              <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <DiagCard label="Nodes Touched" value={nodeSummaries.length} />
                <DiagCard label="Completed Steps" value={completedSteps} />
                <DiagCard label="Failed Steps" value={failedSteps} />
                <DiagCard label="Paused Nodes" value={pausedNodes} />
              </div>
              {nodeSummaries.length > 0 && (
                <div className="mb-5 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-gray-900">Node Execution Report</h4>
                    <p className="text-xs text-gray-500">Per-node summary of starts, completions, pauses, and failures.</p>
                  </div>
                  <div className="space-y-3">
                    {nodeSummaries.map((summary) => (
                      <NodeExecutionCard key={summary.nodeId} summary={summary} />
                    ))}
                  </div>
                </div>
              )}
              <div ref={timelineRef} className="max-h-[500px] space-y-1.5 overflow-y-auto">
                {filteredEvents.length === 0 ? (
                  <p className="text-sm text-gray-400">No events match this filter</p>
                ) : (
                  filteredEvents.map((event) => {
                    const hasPayload = event.payload && Object.keys(event.payload).length > 0;
                    const errStyle = isError(event.event_type);
                    // Error events auto-expand; others expand on demand
                    const expanded = errStyle || expandedEvents.has(String(event.event_id));
                    const inlineErr = errStyle ? extractErrorMessage(event.payload) : null;
                    const highlights = getEventHighlights(event);
                    const isStepEvent = event.event_type.startsWith("step_") || event.event_type === "llm_usage";
                    const isNodeEvent = event.event_type.startsWith("node_");
                    const isRunEvent = event.event_type.startsWith("run_") || event.event_type === "execution_started" || event.event_type === "execution_resumed";
                    return (
                      <div
                        key={event.event_id}
                        className={`rounded-lg border p-3 ${errStyle
                          ? "border-red-200 bg-red-50"
                          : isRunEvent
                            ? "border-blue-100 bg-blue-50/40"
                            : isNodeEvent
                              ? "border-purple-100 bg-purple-50/30"
                              : "border-gray-100 bg-white"
                          } ${isStepEvent ? "ml-4" : ""}`}
                      >
                        <div className="flex items-center gap-2">
                          <EventDot type={event.event_type} />
                          <span className={`text-xs font-semibold ${errStyle ? "text-red-700" : isRunEvent ? "text-blue-800" : isNodeEvent ? "text-purple-700" : "text-gray-800"}`}>
                            {eventLabel(event.event_type)}
                          </span>
                          {/* raw type as a subtle hint */}
                          <span className="text-[9px] text-gray-300 font-mono hidden sm:inline">{event.event_type}</span>
                          {event.node_id && (() => {
                            const payloadNodeName = (event.payload as Record<string, unknown> | null)?.node_name;
                            const nodeName = typeof payloadNodeName === "string" ? payloadNodeName : null;
                            const nameIsDifferent = nodeName && nodeName !== event.node_id;
                            return (
                              <>
                                {/* Always show node_id as a grey mono badge */}
                                <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] text-gray-500">
                                  {event.node_id}
                                </span>
                                {/* Show node_name as a readable purple badge when it differs from node_id */}
                                {nameIsDifferent && (
                                  <span className="rounded bg-purple-50 border border-purple-100 px-1.5 py-0.5 text-[10px] text-purple-700" title="node name">
                                    {nodeName}
                                  </span>
                                )}
                              </>
                            );
                          })()}
                          {event.step_id && (
                            <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-500">
                              {event.step_id}
                            </span>
                          )}
                          {event.attempt != null && event.attempt > 0 && (
                            <span className="rounded bg-yellow-50 px-1.5 py-0.5 text-[10px] text-yellow-600">
                              retry #{event.attempt}
                            </span>
                          )}
                          {event.event_type === "step_completed" && typeof event.payload?.duration_ms === "number" && (
                            <span className="rounded bg-green-50 px-1.5 py-0.5 text-[10px] text-green-600">
                              {Number(event.payload.duration_ms)}ms
                            </span>
                          )}
                          {/* D1: retry_count badge */}
                          {event.event_type === "step_completed" && typeof (event.payload as Record<string, unknown>)?.retry_count === "number" && Number((event.payload as Record<string, unknown>).retry_count) > 0 && (
                            <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                              🔄 {Number((event.payload as Record<string, unknown>).retry_count)} retries
                            </span>
                          )}
                          {/* D2: step_timeout icon */}
                          {event.event_type === "step_timeout" && (
                            <span className="rounded bg-orange-50 px-1.5 py-0.5 text-[10px] font-semibold text-orange-700">
                              ⏱ Timeout
                            </span>
                          )}
                          {/* G2: loop_iteration progress */}
                          {event.event_type === "loop_iteration" && event.payload && (
                            <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-700">
                              ↻ {Number((event.payload as Record<string, unknown>).iteration) + 1}/{Number((event.payload as Record<string, unknown>).total)}
                            </span>
                          )}
                          {/* F2: agent binding in timeline */}
                          {Boolean((event.payload as Record<string, unknown>)?.agent) && (
                            <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-600">
                              🤖 {String((event.payload as Record<string, unknown>).agent)}
                            </span>
                          )}
                          <span className="ml-auto text-[10px] text-gray-300 flex-shrink-0">
                            {new Date(event.created_at).toLocaleTimeString()}
                          </span>
                          {hasPayload && !errStyle && (
                            <button
                              onClick={() =>
                                setExpandedEvents((prev) => {
                                  const n = new Set(prev);
                                  n.has(String(event.event_id))
                                    ? n.delete(String(event.event_id))
                                    : n.add(String(event.event_id));
                                  return n;
                                })
                              }
                              className="text-[10px] text-gray-400 hover:text-gray-700 flex-shrink-0"
                            >
                              {expandedEvents.has(String(event.event_id)) ? "▲" : "▼"}
                            </button>
                          )}
                        </div>
                        {/* Inline error message — always shown for error events */}
                        {inlineErr && (
                          <p className="mt-1.5 text-xs text-red-600 font-medium break-words">{inlineErr}</p>
                        )}
                        {!inlineErr && highlights.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {highlights.map((highlight, index) => (
                              <span key={`${event.event_id}-${index}`} className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">
                                {highlight}
                              </span>
                            ))}
                          </div>
                        )}
                        {/* Payload detail */}
                        {hasPayload && expanded && !inlineErr && (
                          event.event_type === "llm_usage" ? (
                            <LlmUsageDetail payload={event.payload} />
                          ) : (
                            <pre className="mt-2 max-h-48 overflow-auto rounded bg-gray-50 p-2 font-mono text-xs text-gray-600">
                              {JSON.stringify(event.payload, null, 2)}
                            </pre>
                          )
                        )}
                        {/* Full payload toggle for errors (below inline message) */}
                        {hasPayload && errStyle && (
                          <details className="mt-1">
                            <summary className="cursor-pointer text-[10px] text-red-400 hover:text-red-600">
                              {expandedEvents.has(String(event.event_id)) ? "▲ hide payload" : "▼ full payload"}
                            </summary>
                            <pre className="mt-1 max-h-48 overflow-auto rounded bg-red-50 p-2 font-mono text-xs text-red-700">
                              {JSON.stringify(event.payload, null, 2)}
                            </pre>
                          </details>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </>
          )}

          {/* Graph with execution overlay */}
          {activeTab === "graph" && (
            <>
              {!graphData ? (
                <p className="text-sm text-gray-400">Loading graph…</p>
              ) : (
                <>
                  <div className="mb-3 flex flex-wrap gap-3 text-xs text-gray-500">
                    {([["in_progress", "bg-blue-500"], ["completed", "bg-green-500"], ["pending", "bg-gray-400"], ["failed", "bg-red-500"], ["sla_breached", "bg-orange-400"]] as const).map(([s, bg]) => (
                      <span key={s} className="flex items-center gap-1"><span className={`h-3 w-3 rounded-full ${bg}`} />{s.replace("_", " ")}</span>
                    ))}
                  </div>
                  <WorkflowGraph graph={graphData as any} nodeStates={nodeStateMap} edgeCounts={edgeTraversalCounts} />
                </>
              )}
            </>
          )}

          {/* Artifacts */}
          {activeTab === "artifacts" && (
            <>
              {artifactNotice && <span className="mb-3 inline-block rounded-md bg-green-50 px-2 py-1 text-xs font-medium text-green-700">New artifact received</span>}
              {artifacts.length === 0 ? (
                <p className="text-sm text-gray-400">No artifacts captured</p>
              ) : (
                <div className="space-y-2">
                  {artifacts.map((a) => {
                    const isPreviewable = /\.(json|txt|log|md|csv|xml|yaml|yml)$/i.test(a.uri) || a.kind === "json" || a.kind === "text" || a.kind === "log";
                    const isImage = /\.(png|jpg|jpeg|gif|svg|webp)$/i.test(a.uri) || a.kind === "screenshot" || a.kind === "image";
                    return (
                      <div key={a.artifact_id} className="rounded-lg border border-gray-100 p-3">
                        <div className="flex items-center justify-between">
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-gray-900">{a.kind}</p>
                            <p className="truncate text-xs text-gray-500">{a.node_id ? `node: ${a.node_id}` : "—"}{a.step_id ? ` | step: ${a.step_id}` : ""}</p>
                          </div>
                          <div className="flex items-center gap-2">
                            <a href={a.uri} target="_blank" rel="noreferrer" className="text-xs text-primary-600 hover:underline">Open</a>
                            <a href={a.uri} download className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50">↓ Download</a>
                          </div>
                        </div>
                        {/* Inline preview */}
                        {isImage && (
                          <div className="mt-2 rounded-lg border border-gray-100 bg-gray-50 p-2">
                            <img src={a.uri} alt={a.kind} className="max-h-48 rounded" />
                          </div>
                        )}
                        {isPreviewable && <ArtifactPreview uri={a.uri} />}
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {/* Checkpoints */}
          {activeTab === "checkpoints" && (
            <>
              {checkpoints.length === 0 ? (
                <p className="text-sm text-gray-400">No checkpoints captured for this run</p>
              ) : (
                <div className="space-y-3">
                  <div className="overflow-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-gray-500 text-xs">
                          <th className="pb-2 pr-4">Step</th>
                          <th className="pb-2 pr-4">Checkpoint ID</th>
                          <th className="pb-2 pr-4">Parent</th>
                          <th className="pb-2 pr-4">Created</th>
                          <th className="pb-2">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {checkpoints.map((ckpt, idx) => (
                          <tr key={ckpt.checkpoint_id ?? idx} className="border-b last:border-0 hover:bg-gray-50">
                            <td className="py-2 pr-4 font-mono text-xs">{ckpt.step}</td>
                            <td className="py-2 pr-4 font-mono text-xs">{ckpt.checkpoint_id ? ckpt.checkpoint_id.slice(0, 12) + "…" : "—"}</td>
                            <td className="py-2 pr-4 font-mono text-xs text-gray-400">{ckpt.parent_checkpoint_id ? ckpt.parent_checkpoint_id.slice(0, 12) + "…" : "—"}</td>
                            <td className="py-2 pr-4 text-xs text-gray-500">{ckpt.created_at ? new Date(ckpt.created_at).toLocaleString() : "—"}</td>
                            <td className="py-2">
                              <button
                                onClick={async () => {
                                  if (!ckpt.checkpoint_id) return;
                                  setLoadingCkpt(true);
                                  try {
                                    const state = await getCheckpointState(runId, ckpt.checkpoint_id);
                                    setSelectedCkpt(state);
                                  } catch { toast("Failed to load checkpoint state", "error"); }
                                  finally { setLoadingCkpt(false); }
                                }}
                                disabled={!ckpt.checkpoint_id || loadingCkpt}
                                className="rounded border border-primary-300 px-2 py-0.5 text-xs text-primary-600 hover:bg-primary-50 disabled:opacity-40"
                              >
                                Inspect
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {/* Checkpoint state detail */}
                  {selectedCkpt && (
                    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                      <div className="mb-3 flex items-center justify-between">
                        <h4 className="text-sm font-semibold text-blue-800">Checkpoint State — {selectedCkpt.checkpoint_id?.slice(0, 16)}…</h4>
                        <button onClick={() => setSelectedCkpt(null)} className="text-xs text-blue-500 hover:text-blue-700">Close</button>
                      </div>
                      <div className="space-y-3">
                        <div>
                          <p className="mb-1 text-xs font-semibold text-blue-700">Channel Values</p>
                          <pre className="max-h-64 overflow-auto rounded-lg bg-white p-3 font-mono text-xs text-gray-700">{JSON.stringify(selectedCkpt.channel_values, null, 2)}</pre>
                        </div>
                        {selectedCkpt.pending_writes.length > 0 && (
                          <div>
                            <p className="mb-1 text-xs font-semibold text-blue-700">Pending Writes</p>
                            <pre className="max-h-48 overflow-auto rounded-lg bg-white p-3 font-mono text-xs text-gray-700">{JSON.stringify(selectedCkpt.pending_writes, null, 2)}</pre>
                          </div>
                        )}
                        {Object.keys(selectedCkpt.metadata).length > 0 && (
                          <div>
                            <p className="mb-1 text-xs font-semibold text-blue-700">Metadata</p>
                            <pre className="max-h-48 overflow-auto rounded-lg bg-white p-3 font-mono text-xs text-gray-700">{JSON.stringify(selectedCkpt.metadata, null, 2)}</pre>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {/* Diagnostics */}
          {activeTab === "diagnostics" && (
            <>
              {!diagnostics ? (
                <p className="text-sm text-gray-400">Loading diagnostics…</p>
              ) : (
                <div className="space-y-5">
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <DiagCard label="Total Events" value={diagnostics.total_events} />
                    <DiagCard label="Error Events" value={diagnostics.error_events} />
                    <DiagCard label="Has Retry" value={diagnostics.has_retry_event ? "Yes" : "No"} />
                    <DiagCard label="Idempotency Rows" value={diagnostics.idempotency_entries.length} />
                  </div>
                  {diagnostics.active_leases.length > 0 && (
                    <div>
                      <h4 className="mb-2 text-xs font-semibold text-gray-700">Active Leases</h4>
                      <div className="space-y-1">
                        {diagnostics.active_leases.map((l) => (
                          <div key={l.lease_id} className="rounded bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
                            <span className="font-medium">{l.resource_key}</span>
                            {l.node_id && <span className="ml-2 text-yellow-600">node: {l.node_id}</span>}
                            <span className="ml-2 text-yellow-500">expires: {new Date(l.expires_at).toLocaleTimeString()}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {diagnostics.idempotency_entries.length > 0 && (
                    <div>
                      <h4 className="mb-2 text-xs font-semibold text-gray-700">Idempotency Cache</h4>
                      <div className="overflow-auto">
                        <table className="w-full text-xs">
                          <thead><tr className="border-b text-left text-gray-500"><th className="pb-1 pr-3">Node</th><th className="pb-1 pr-3">Step</th><th className="pb-1 pr-3">Key</th><th className="pb-1 pr-3">Status</th><th className="pb-1 pr-3">Cached</th><th className="pb-1">Updated</th></tr></thead>
                          <tbody>
                            {diagnostics.idempotency_entries.map((e) => (
                              <tr key={`${e.node_id}:${e.step_id}`} className="border-b last:border-0">
                                <td className="py-1 pr-3 font-mono">{e.node_id}</td>
                                <td className="py-1 pr-3 font-mono">{e.step_id}</td>
                                <td className="py-1 pr-3 font-mono text-gray-400 max-w-[120px] truncate" title={e.idempotency_key ?? undefined}>{e.idempotency_key ?? "—"}</td>
                                <td className="py-1 pr-3">{e.status}</td>
                                <td className="py-1 pr-3">{e.has_cached_result ? <span className="rounded bg-green-50 px-1 text-green-600">cached</span> : <span className="text-gray-400">—</span>}</td>
                                <td className="py-1 text-gray-400">{e.updated_at ? new Date(e.updated_at).toLocaleTimeString() : "—"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Retry with modified inputs modal */}
      {showRetryModal && run && (() => {
        const schema = flattenVariablesSchema((procedureDetail?.ckp_json as any)?.variables_schema ?? {});
        const schemaEntries = Object.entries(schema) as [string, any][];
        // Include extra vars from original run not in schema
        const extraKeys = Object.keys(retryVarsForm).filter((k) => !schema[k]);
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
            <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
              <h3 className="mb-1 text-base font-semibold text-gray-900">Retry with Modified Inputs</h3>
              <p className="mb-4 text-xs text-gray-500">Edit input variables before creating a new run from this failed run.</p>
              <div className="max-h-[60vh] overflow-y-auto space-y-4 pr-1">
                {schemaEntries.map(([key, meta]) => {
                  const validation = (meta?.validation ?? {}) as Record<string, any>;
                  const allowed = validation.allowed_values as string[] | undefined;
                  const isRequired = !!meta?.required;
                  const isSensitive = isFieldSensitive(meta as Record<string, unknown>);
                  const fieldErr = retryVarsErrors[key];
                  const borderCls = fieldErr ? "border-red-400 focus:border-red-500" : "border-gray-300 focus:border-primary-500";
                  return (
                    <div key={key}>
                      <label className="mb-1 block text-xs font-medium text-gray-600">
                        {key}
                        {meta?.type && <span className="ml-1 text-gray-400">({meta.type})</span>}
                        {isRequired && <span className="ml-1 text-red-500">*</span>}
                        {isSensitive && <span className="ml-1 text-yellow-600">🔒</span>}
                      </label>
                      {meta?.description && <p className="mb-1 text-xs text-gray-400">{meta.description}</p>}
                      {allowed ? (
                        <select
                          value={retryVarsForm[key] ?? ""}
                          onChange={(e) => handleRetryVarChange(key, e.target.value, meta)}
                          aria-label={key}
                          className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}
                        >
                          <option value="">— select —</option>
                          {allowed.map((v: string) => (<option key={v} value={v}>{v}</option>))}
                        </select>
                      ) : meta?.type === "array" || meta?.type === "object" ? (
                        <textarea
                          value={retryVarsForm[key] ?? ""}
                          onChange={(e) => handleRetryVarChange(key, e.target.value, meta)}
                          placeholder={meta?.type === "array" ? '["item1","item2"]' : '{"key":"value"}'}
                          rows={3}
                          className={`w-full rounded-lg border p-2 text-sm focus:outline-none font-mono ${borderCls}`}
                        />
                      ) : (
                        <input
                          type={isSensitive ? "password" : meta?.type === "number" ? "number" : "text"}
                          value={retryVarsForm[key] ?? ""}
                          onChange={(e) => handleRetryVarChange(key, e.target.value, meta)}
                          placeholder={meta?.default !== undefined && !isSensitive ? String(meta.default) : ""}
                          autoComplete="off"
                          aria-label={key}
                          className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}
                        />
                      )}
                      {fieldErr && <p className="mt-1 text-xs text-red-500">{fieldErr}</p>}
                    </div>
                  );
                })}
                {/* Extra fields from original run not in schema */}
                {extraKeys.map((key) => (
                  <div key={key}>
                    <label className="mb-1 block text-xs font-medium text-gray-600">{key} <span className="text-gray-400">(extra)</span></label>
                    <input
                      type="text"
                      value={retryVarsForm[key] ?? ""}
                      onChange={(e) => setRetryVarsForm((prev) => ({ ...prev, [key]: e.target.value }))}
                      aria-label={key}
                      placeholder={key}
                      className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                    />
                  </div>
                ))}
                {schemaEntries.length === 0 && extraKeys.length === 0 && (
                  <p className="text-sm text-gray-400">No input variables defined for this procedure.</p>
                )}
              </div>
              <div className="mt-5 flex gap-2">
                <button
                  onClick={() => {
                    // Validate
                    const allErrors: Record<string, string> = {};
                    schemaEntries.forEach(([k, meta]) => {
                      const e = validateRetryField(k, retryVarsForm[k] ?? "", meta);
                      if (e) allErrors[k] = e;
                    });
                    if (Object.keys(allErrors).length > 0) {
                      setRetryVarsErrors(allErrors);
                      return;
                    }
                    // Parse values
                    const parsed: Record<string, unknown> = {};
                    let parseError = false;
                    schemaEntries.forEach(([k, meta]) => {
                      const raw = retryVarsForm[k];
                      if (meta?.type === "array" || meta?.type === "object") {
                        if (!raw) return; // blank optional field — omit
                        try { parsed[k] = JSON.parse(raw); } catch {
                          toast(`Invalid JSON for "${k}" — expected ${meta.type === "array" ? "[...]" : "{...}"}`, "error");
                          parseError = true;
                        }
                      } else {
                        parsed[k] = meta?.type === "number" ? Number(raw) : raw;
                      }
                    });
                    // Include extras
                    extraKeys.forEach((k) => { parsed[k] = retryVarsForm[k]; });
                    if (parseError) return;
                    setShowRetryModal(false);
                    void doRetryRun(parsed);
                  }}
                  disabled={retryCreating || Object.keys(retryVarsErrors).length > 0}
                  className="flex-1 rounded-lg bg-primary-600 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                >
                  {retryCreating ? "Creating…" : "Retry with Changes"}
                </button>
                <button
                  onClick={() => setShowRetryModal(false)}
                  className="flex-1 rounded-lg border border-gray-300 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

/* ── Sub-components ─────────────────────────────────────────── */

function ClipboardIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3" />
    </svg>
  );
}

function RunStatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    running: "bg-blue-100 text-blue-700",
    created: "bg-gray-100 text-gray-600",
    waiting_approval: "bg-yellow-100 text-yellow-700",
    canceled: "bg-gray-200 text-gray-500",
    cancelled: "bg-gray-200 text-gray-500",
  };
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${map[status] ?? "bg-gray-100 text-gray-600"}`}>{status}</span>;
}

function InfoCard({ label, value, onCopy }: { label: string; value: string; onCopy?: () => void }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <p className="text-xs text-gray-500">{label}</p>
      <div className="mt-1 flex items-center gap-1">
        <p className="text-sm font-medium text-gray-900 truncate">{value}</p>
        {onCopy && <button onClick={onCopy} className="flex-shrink-0 text-gray-300 hover:text-gray-600" title="Copy"><ClipboardIcon /></button>}
      </div>
    </div>
  );
}

function EventDot({ type }: { type: string }) {
  const colors: Record<string, string> = {
    run_created: "bg-blue-400", execution_started: "bg-blue-300", execution_resumed: "bg-blue-400",
    node_started: "bg-yellow-400", node_paused: "bg-orange-300",
    node_completed: "bg-green-400", step_started: "bg-gray-300", step_completed: "bg-green-300",
    error: "bg-red-400", approval_requested: "bg-orange-400", approval_decided: "bg-purple-400",
    approval_decide_received: "bg-purple-300", approval_decision_received: "bg-purple-300",
    run_completed: "bg-green-600", run_failed: "bg-red-600", step_timeout: "bg-orange-500",
    sla_breached: "bg-red-300", node_error: "bg-red-500", approval_expired: "bg-gray-500",
    run_retry_requested: "bg-indigo-400", dry_run_step_skipped: "bg-gray-400", checkpoint_saved: "bg-teal-400",
    llm_usage: "bg-purple-300", loop_iteration: "bg-indigo-300", step_error_notification: "bg-red-400",
  };
  return <div className={`mt-0.5 h-2 w-2 flex-shrink-0 rounded-full ${colors[type] ?? "bg-gray-300"}`} />;
}

function DiagCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
      <p className="text-[10px] text-gray-500">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-gray-800">{value}</p>
    </div>
  );
}

function NodeExecutionCard({ summary }: { summary: NodeExecutionSummary }) {
  const completedSteps = summary.steps.filter((step) => step.status === "completed" || step.status === "cached").length;
  const failedSteps = summary.steps.filter((step) => step.status === "failed" || step.status === "timeout").length;
  const stateTone: Record<NodeExecutionSummary["status"], string> = {
    running: "bg-blue-50 text-blue-700 border-blue-200",
    completed: "bg-green-50 text-green-700 border-green-200",
    failed: "bg-red-50 text-red-700 border-red-200",
    sla_breached: "bg-orange-50 text-orange-700 border-orange-200",
    current: "bg-blue-50 text-blue-700 border-blue-200",
    pending: "bg-gray-50 text-gray-600 border-gray-200",
    paused: "bg-amber-50 text-amber-700 border-amber-200",
  };

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-gray-900">{summary.nodeName ?? summary.nodeId}</p>
            <span className="rounded bg-gray-100 px-2 py-0.5 font-mono text-[11px] text-gray-600">{summary.nodeId}</span>
            <span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${stateTone[summary.status]}`}>{summary.status.replace(/_/g, " ")}</span>
            {summary.approvalId && <span className="rounded-full bg-purple-50 px-2 py-0.5 text-[11px] text-purple-700">approval {summary.approvalId.slice(0, 12)}...</span>}
          </div>
          {summary.error && <p className="text-xs text-red-600">{summary.error}</p>}
          {summary.pauseReason && <p className="text-xs text-amber-700">Pause reason: {summary.pauseReason}</p>}
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <DiagCard label="Started" value={formatTimestamp(summary.startedAt)} />
          <DiagCard label={summary.finishedAt ? "Finished" : "Last Update"} value={formatTimestamp(summary.finishedAt ?? summary.lastUpdatedAt)} />
          <DiagCard label="Completed Steps" value={completedSteps} />
          <DiagCard label="Failed Steps" value={failedSteps} />
        </div>
      </div>
      {summary.steps.length > 0 && (
        <div className="mt-4 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b text-gray-500">
                <th className="pb-2 pr-3">Step</th>
                <th className="pb-2 pr-3">Action</th>
                <th className="pb-2 pr-3">Status</th>
                <th className="pb-2 pr-3">Started</th>
                <th className="pb-2 pr-3">Finished</th>
                <th className="pb-2 pr-3">Duration</th>
                <th className="pb-2">Notes</th>
              </tr>
            </thead>
            <tbody>
              {summary.steps.map((step) => (
                <tr key={`${summary.nodeId}-${step.stepId}`} className="border-b last:border-0 align-top">
                  <td className="py-2 pr-3 font-mono text-gray-700">{step.stepId}</td>
                  <td className="py-2 pr-3 text-gray-600">{step.action ?? "-"}</td>
                  <td className="py-2 pr-3">
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-700">{step.status}</span>
                  </td>
                  <td className="py-2 pr-3 text-gray-500">{formatTimestamp(step.startedAt)}</td>
                  <td className="py-2 pr-3 text-gray-500">{formatTimestamp(step.completedAt)}</td>
                  <td className="py-2 pr-3 text-gray-500">{formatMilliseconds(step.durationMs)}</td>
                  <td className="py-2 text-gray-500">
                    {step.retryCount > 0 ? `retries ${step.retryCount}` : step.error ?? "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LlmUsageDetail({ payload }: { payload: Record<string, unknown> }) {
  return (
    <div className="mt-2 flex flex-wrap gap-2 rounded-lg border border-purple-100 bg-purple-50 p-2">
      {payload.model != null && (
        <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-[10px] font-medium text-purple-700">
          {String(payload.model)}
        </span>
      )}
      {payload.prompt_tokens != null && (
        <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-[10px] font-medium text-blue-600">
          prompt: <strong>{String(payload.prompt_tokens)}</strong> tok
        </span>
      )}
      {payload.completion_tokens != null && (
        <span className="rounded-full bg-green-50 px-2.5 py-0.5 text-[10px] font-medium text-green-600">
          completion: <strong>{String(payload.completion_tokens)}</strong> tok
        </span>
      )}
      {payload.total_tokens != null && (
        <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-[10px] font-medium text-gray-600">
          total: <strong>{String(payload.total_tokens)}</strong> tok
        </span>
      )}
    </div>
  );
}

function ArtifactPreview({ uri }: { uri: string }) {
  const [content, setContent] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);

  async function loadPreview() {
    if (content !== null) { setExpanded(!expanded); return; }
    setLoading(true);
    try {
      const res = await fetch(uri);
      if (!res.ok) throw new Error("Failed to fetch");
      const text = await res.text();
      // Try to parse as JSON and pretty-print
      try {
        const parsed = JSON.parse(text);
        setContent(JSON.stringify(parsed, null, 2));
      } catch {
        setContent(text);
      }
      setExpanded(true);
    } catch {
      setContent("Failed to load preview");
      setExpanded(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-2">
      <button
        onClick={loadPreview}
        disabled={loading}
        className="text-[10px] text-gray-400 hover:text-gray-700"
      >
        {loading ? "Loading…" : expanded ? "▲ Hide preview" : "▼ Preview"}
      </button>
      {expanded && content !== null && (
        <pre className="mt-1 max-h-48 overflow-auto rounded-lg bg-gray-50 p-2 font-mono text-xs text-gray-600">{content}</pre>
      )}
    </div>
  );
}
