"use client";

/**
 * WorkflowBuilder — visual drag-and-drop CKP workflow editor.
 *
 * Features:
 *  • Node palette – click a type button to add a node to the canvas
 *  • Editable nodes – click a node to open the inspector panel
 *  • Edge connections – drag from the bottom Handle to another node's top Handle
 *  • Edge labels – click an edge to set its label (approve/reject/timeout/true/false …)
 *  • Delete – select a node or edge and press Backspace / Delete
 *  • Start node – click "Set as Start" in the inspector
 *  • Auto-layout – re-runs dagre layout
 *  • Export – converts the canvas back to a CKP workflow_graph object
 *  • Import – initialises the canvas from an existing CKP workflow_graph
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  Panel,
  MarkerType,
  BackgroundVariant,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  type Node,
  type Edge,
  type NodeProps,
  type NodeChange,
  type EdgeChange,
  type Connection,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";

// ─── Constants ───────────────────────────────────────────────────────────────

const NODE_TYPES_LIST = [
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

type CkpNodeType = (typeof NODE_TYPES_LIST)[number];

const TYPE_ICONS: Record<string, string> = {
  sequence:       "▶",
  logic:          "◇",
  loop:           "↻",
  parallel:       "⫽",
  human_approval: "✋",
  llm_action:     "🤖",
  processing:     "⚙",
  verification:   "✓",
  transform:      "⇌",
  subflow:        "↗",
  terminate:      "⏹",
};

const TYPE_BG: Record<string, string> = {
  // ── Deterministic (Blue tier) ──
  sequence:       "#3B82F6",
  processing:     "#2563EB",
  transform:      "#1D4ED8",
  subflow:        "#60A5FA",
  // ── Intelligent (Purple tier) ──
  llm_action:     "#7C3AED",
  // ── Control (Orange tier) ──
  loop:           "#F97316",
  parallel:       "#EA580C",
  logic:          "#F59E0B",
  verification:   "#D97706",
  human_approval: "#EF4444",
  terminate:      "#6B7280",
};

// ── 3-tier node categories ────────────────────────────────────────────────────
type NodeCategory = "deterministic" | "intelligent" | "control";

const TYPE_CATEGORY: Record<string, NodeCategory> = {
  sequence:       "deterministic",
  processing:     "deterministic",
  transform:      "deterministic",
  subflow:        "deterministic",
  llm_action:     "intelligent",
  loop:           "control",
  parallel:       "control",
  logic:          "control",
  verification:   "control",
  human_approval: "control",
  terminate:      "control",
};

const CATEGORY_META: Record<NodeCategory, { label: string; color: string; description: string; badge: string }> = {
  deterministic: {
    label: "Deterministic",
    color: "#3B82F6",
    description: "API calls, data operations, transforms, subflows",
    badge: "bg-blue-100 text-blue-700",
  },
  intelligent: {
    label: "Intelligent",
    color: "#7C3AED",
    description: "LLM actions, agents, AI reasoning",
    badge: "bg-purple-100 text-purple-700",
  },
  control: {
    label: "Control",
    color: "#F97316",
    description: "Logic, loops, approvals, human-in-the-loop",
    badge: "bg-orange-100 text-orange-700",
  },
};

const NODE_PALETTE_GROUPS: Array<{ category: NodeCategory; types: CkpNodeType[] }> = [
  { category: "deterministic", types: ["sequence", "processing", "transform", "subflow"] },
  { category: "intelligent",   types: ["llm_action"] },
  { category: "control",       types: ["loop", "parallel", "logic", "verification", "human_approval", "terminate"] },
];

// ── Workflow templates ────────────────────────────────────────────────────────
interface WorkflowTemplate {
  name: string;
  description: string;
  icon: string;
  workflowGraph: Record<string, unknown>;
}

const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    name: "Invoice Processing",
    description: "Extract fields, validate, then route to approval or rejection",
    icon: "🧾",
    workflowGraph: {
      start_node: "extract_fields",
      nodes: {
        extract_fields:   { type: "llm_action",     description: "Extract invoice fields via LLM", next_node: "validate_fields" },
        validate_fields:  { type: "processing",     description: "Validate extracted fields", on_pass: "request_approval", on_fail: "flag_invalid" },
        request_approval: { type: "human_approval", description: "Manager approves invoice", on_approve: "process_payment", on_reject: "flag_invalid" },
        process_payment:  { type: "sequence",       description: "POST to payment API", next_node: "done" },
        flag_invalid:     { type: "sequence",       description: "Log invalid invoice", next_node: "done" },
        done:             { type: "terminate",      status: "success" },
      },
    },
  },
  {
    name: "Customer Support",
    description: "Classify inquiry, route to specialist or auto-reply",
    icon: "💬",
    workflowGraph: {
      start_node: "classify_inquiry",
      nodes: {
        classify_inquiry: { type: "llm_action", description: "Classify customer inquiry type", next_node: "route" },
        route:            { type: "logic",      description: "Route by inquiry category", on_true: "auto_reply", on_false: "specialist_queue" },
        auto_reply:       { type: "llm_action", description: "Generate and send auto reply", next_node: "done" },
        specialist_queue: { type: "sequence",   description: "Enqueue for human specialist", next_node: "await_specialist" },
        await_specialist: { type: "human_approval", description: "Specialist resolves ticket", on_approve: "done", on_reject: "escalate" },
        escalate:         { type: "sequence",   description: "Escalate to senior support", next_node: "done" },
        done:             { type: "terminate",  status: "success" },
      },
    },
  },
  {
    name: "Contract Review",
    description: "Summarise, check compliance, flag risks, require sign-off",
    icon: "📄",
    workflowGraph: {
      start_node: "summarise",
      nodes: {
        summarise:      { type: "llm_action",     description: "Summarise contract clauses", next_node: "compliance_check" },
        compliance_check: { type: "llm_action",  description: "Check against compliance rules", next_node: "risk_score" },
        risk_score:     { type: "processing",     description: "Compute risk score", on_pass: "legal_review", on_fail: "flag_risks" },
        flag_risks:     { type: "sequence",       description: "Log and notify risk owner", next_node: "legal_review" },
        legal_review:   { type: "human_approval", description: "Legal signs off contract", on_approve: "archive", on_reject: "revise" },
        revise:         { type: "sequence",       description: "Send back for revision", next_node: "done" },
        archive:        { type: "sequence",       description: "Archive approved contract", next_node: "done" },
        done:           { type: "terminate",      status: "success" },
      },
    },
  },
  {
    name: "Agentic Orchestration",
    description: "Agent analyses input and dynamically picks the next step — no hard-coded routing",
    icon: "🧠",
    workflowGraph: {
      start_node: "ingest",
      nodes: {
        ingest: {
          type: "sequence",
          description: "Fetch and normalise input data",
          next_node: "agent_router",
        },
        agent_router: {
          type: "llm_action",
          description: "Analyse context and choose the best next action",
          model: "gpt-4o",
          orchestration_mode: true,
          branches: ["deep_analysis", "quick_summary", "escalate_human"],
          prompt: "Given the following data: {{vars.input}}\nDecide which action is most appropriate and return JSON with the field '_next_node'.",
          system_prompt: "You are a workflow orchestrator. Evaluate the inputs and select the best processing path.",
        },
        deep_analysis: {
          type: "llm_action",
          description: "Thorough multi-step analysis",
          next_node: "compile_report",
        },
        quick_summary: {
          type: "llm_action",
          description: "Fast high-level summary",
          next_node: "compile_report",
        },
        escalate_human: {
          type: "human_approval",
          description: "Needs human judgment — route to specialist",
          on_approve: "compile_report",
          on_reject: "compile_report",
        },
        compile_report: {
          type: "processing",
          description: "Compile final report",
          on_pass: "done",
          on_fail: "done",
        },
        done: { type: "terminate", status: "success" },
      },
    },
  },
];

const NODE_W = 244;
const NODE_H = 116;

// ─── Edge label to CKP key mapping ───────────────────────────────────────────

const EDGE_LABEL_OPTIONS = [
  { value: "",          label: "→ next (default flow)" },
  { value: "approve",   label: "✓ approve" },
  { value: "reject",    label: "✕ reject" },
  { value: "timeout",   label: "⏱ timeout" },
  { value: "true",      label: "◎ true / yes" },
  { value: "false",     label: "○ false / no" },
  { value: "default",   label: "— default" },
  { value: "pass",      label: "✓ pass" },
  { value: "fail",      label: "✕ fail" },
  { value: "error",     label: "⚠ error" },
  { value: "loop body", label: "↻ loop body" },
];

function edgeColor(label: string | undefined) {
  const l = (label ?? "").toLowerCase();
  if (l === "approve" || l === "true" || l === "pass" || l === "yes") return "#22C55E";
  if (l === "reject" || l === "false" || l === "fail" || l === "no") return "#EF4444";
  if (l === "timeout" || l === "error") return "#F97316";
  if (l === "default") return "#9CA3AF";
  if (l === "loop body") return "#8B5CF6";
  return "#6366F1";
}

// ─── Dagre layout ────────────────────────────────────────────────────────────

function dagreLayout(
  nodes: Array<{ id: string }>,
  edges: Array<{ source: string; target: string }>,
): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 72, ranksep: 100, marginx: 40, marginy: 40 });
  for (const n of nodes) g.setNode(n.id, { width: NODE_W, height: NODE_H });
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  const out = new Map<string, { x: number; y: number }>();
  for (const n of nodes) {
    const p = g.node(n.id);
    if (p) out.set(n.id, { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 });
  }
  return out;
}

// ─── Builder node data ───────────────────────────────────────────────────────

export interface BuilderNodeData {
  label: string;          // CKP node key / ID (e.g. "init", "approve_step")
  nodeType: string;
  description: string;
  agent: string;
  isStart: boolean;
  isCheckpoint: boolean;
  // terminate
  status?: string;
  // human_approval
  approvalPrompt?: string;
  decisionType?: string;
  timeoutMs?: number;
  // llm_action
  llmPrompt?: string;
  llmModel?: string;
  orchestrationMode?: boolean;
  orchestrationBranches?: string;
  // loop
  loopMaxIterations?: number;
  loopContinueCondition?: string;
  // parallel
  parallelWaitAll?: boolean;
  // logic
  logicDefaultNext?: string;
  // processing
  action?: string;
  inputMapping?: string;    // JSON text
  outputMapping?: string;   // JSON text
  // transform
  transformer?: string;
  // verification
  verificationRules?: string;  // JSON text
  // subflow
  subflowId?: string;
  subflowVersion?: string;
  // universal
  onFailureNode?: string;
  retryMaxAttempts?: number;
  retryBackoffMs?: number;
  extraJsonText?: string;
  // sequence / WEB — ordered step list
  steps?: Record<string, unknown>[];
  // verification — checks array
  checks?: Record<string, unknown>[];
  // terminate — output variable map
  outputs?: Record<string, unknown>;
  // passthrough: any extra CKP fields not managed visually
  extra?: Record<string, unknown>;
  [key: string]: unknown;
}

// ─── Custom node card (builder variant) ──────────────────────────────────────

function BuilderNode({ data, selected }: NodeProps<Node<BuilderNodeData>>) {
  const { label, nodeType, agent, isStart, description, isCheckpoint, orchestrationMode } = data;
  const color    = TYPE_BG[nodeType] ?? "#9CA3AF";
  const icon     = TYPE_ICONS[nodeType] ?? "●";
  const category = TYPE_CATEGORY[nodeType];
  const catMeta  = category ? CATEGORY_META[category] : null;

  return (
    <>
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: "#D1D5DB", width: 10, height: 10, border: "2px solid #fff" }}
      />
      <div
        className="relative rounded-xl border-2 bg-white transition-shadow duration-150"
        style={{
          borderColor: selected ? "#6366F1" : color,
          boxShadow: selected
            ? "0 0 0 3px rgba(99,102,241,0.3), 0 4px 12px rgba(0,0,0,0.12)"
            : "0 2px 8px rgba(0,0,0,0.07)",
          width: NODE_W,
          minHeight: NODE_H,
        }}
      >
        {/* Accent stripe */}
        <div className="h-[6px] w-full rounded-t-[10px]" style={{ background: color }} />

        <div className="px-3 pt-2 pb-3">
          <div className="flex items-center justify-between gap-1">
            <div className="flex items-center gap-1.5 min-w-0">
              <span
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[11px] text-white"
                style={{ background: color }}
              >
                {icon}
              </span>
              <span className="truncate text-[9px] font-black uppercase tracking-widest text-gray-400">
                {nodeType.replace(/_/g, " ")}
              </span>
            </div>
            {isCheckpoint && (
              <span className="rounded-full bg-purple-100 px-1.5 py-0.5 text-[9px] font-bold text-purple-700">
                ckpt
              </span>
            )}
            {orchestrationMode && (
              <span className="rounded-full bg-purple-700 px-1.5 py-0.5 text-[9px] font-bold text-white" title="Orchestration mode — LLM picks next node">
                🧠 orch
              </span>
            )}
            {catMeta && (
              <span
                className="rounded-full px-1.5 py-0.5 text-[8px] font-bold"
                style={{ background: `${catMeta.color}20`, color: catMeta.color }}
              >
                {catMeta.label.slice(0, 3).toUpperCase()}
              </span>
            )}
          </div>
          <p className="mt-1.5 truncate text-[13px] font-semibold text-gray-800">{label}</p>
          {description && (
            <p className="mt-0.5 text-[10px] leading-tight text-gray-400 line-clamp-2">{description}</p>
          )}
          {agent && (
            <span
              className="mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: `${color}18`, color }}
            >
              🤖 {agent}
            </span>
          )}
          {/* Step / check count badges */}
          <div className="mt-1 flex flex-wrap gap-1">
            {(data.steps as Record<string, unknown>[] | undefined)?.length ? (
              <span className="inline-flex items-center rounded-full bg-blue-50 px-1.5 py-0.5 text-[9px] font-bold text-blue-600">
                {(data.steps as Record<string, unknown>[]).length} steps
              </span>
            ) : null}
            {(data.checks as Record<string, unknown>[] | undefined)?.length ? (
              <span className="inline-flex items-center rounded-full bg-amber-50 px-1.5 py-0.5 text-[9px] font-bold text-amber-600">
                {(data.checks as Record<string, unknown>[]).length} checks
              </span>
            ) : null}
            {(data.outputs as Record<string, unknown> | undefined) && Object.keys(data.outputs as Record<string, unknown>).length > 0 ? (
              <span className="inline-flex items-center rounded-full bg-green-50 px-1.5 py-0.5 text-[9px] font-bold text-green-600">
                {Object.keys(data.outputs as Record<string, unknown>).length} outputs
              </span>
            ) : null}
          </div>
        </div>

        {isStart && (
          <span className="absolute -top-3 left-3 rounded-full bg-emerald-500 px-2 py-0.5 text-[9px] font-black tracking-widest text-white shadow">
            START
          </span>
        )}
        {nodeType === "terminate" && !isStart && (
          <span className="absolute -top-3 left-3 rounded-full bg-gray-500 px-2 py-0.5 text-[9px] font-black tracking-widest text-white shadow">
            END
          </span>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: "#D1D5DB", width: 10, height: 10, border: "2px solid #fff" }}
      />
    </>
  );
}

const nodeTypes = { builderNode: BuilderNode };

// ─── CKP import helpers ──────────────────────────────────────────────────────

function ckpToRf(
  workflowGraph: Record<string, unknown>,
): { nodes: Node<BuilderNodeData>[]; edges: Edge[] } {
  const startNode = (workflowGraph.start_node as string) ?? "";
  const rawNodes = (workflowGraph.nodes as Record<string, Record<string, unknown>>) ?? {};

  const rfNodeList: Node<BuilderNodeData>[] = Object.entries(rawNodes).map(([id, n]) => ({
    id,
    type: "builderNode",
    position: { x: 0, y: 0 }, // will be laid out below
    data: {
      label: id,
      nodeType: (n.type as string) ?? "sequence",
      description: (n.description as string) ?? "",
      agent: (n.agent as string) ?? "",
      isStart: id === startNode,
      isCheckpoint: !!(n.is_checkpoint as boolean),
      status: (n.status as string) ?? "",
      approvalPrompt: (n.prompt as string) ?? "",
      decisionType: (n.decision_type as string) ?? "",
      timeoutMs: n.timeout_ms as number | undefined,
      llmPrompt: (n.prompt as string) ?? "",
      llmModel: (n.model as string) ?? "",
      orchestrationMode: !!(n.orchestration_mode as boolean),
      orchestrationBranches: Array.isArray(n.branches)
        ? (n.branches as string[]).join(", ")
        : (n.branches as string) ?? "",
      // loop
      loopMaxIterations: n.max_iterations as number | undefined,
      loopContinueCondition: (n.continue_condition as string) ?? "",
      // parallel
      parallelWaitAll: n.wait_all !== undefined ? !!(n.wait_all as boolean) : true,
      // logic
      logicDefaultNext: (n.default_next as string) ?? "",
      // processing / transform
      action: (n.action as string) ?? "",
      inputMapping: n.input_mapping ? JSON.stringify(n.input_mapping, null, 2) : "",
      outputMapping: n.output_mapping ? JSON.stringify(n.output_mapping, null, 2) : "",
      // transform
      transformer: (n.transformer as string) ?? "",
      // verification
      verificationRules: Array.isArray(n.rules) || (n.rules && typeof n.rules === "object")
        ? JSON.stringify(n.rules, null, 2) : (n.rules as string) ?? "",
      // subflow
      subflowId: (n.subflow_id as string) ?? "",
      subflowVersion: (n.version as string) ?? "",
      // steps (sequence / WEB nodes)
      steps: Array.isArray(n.steps) ? (n.steps as Record<string, unknown>[]) : [],
      // checks (verification nodes)
      checks: Array.isArray(n.checks) ? (n.checks as Record<string, unknown>[]) : [],
      // outputs (terminate nodes)
      outputs: (n.outputs && typeof n.outputs === "object" && !Array.isArray(n.outputs))
        ? (n.outputs as Record<string, unknown>) : undefined,
      // universal failure / retry
      onFailureNode: typeof n.on_failure === "string" ? n.on_failure : "",
      retryMaxAttempts: (n.retry as Record<string, unknown>)?.max_attempts as number | undefined,
      retryBackoffMs: (n.retry as Record<string, unknown>)?.backoff_ms as number | undefined,
      extra: (({ type, description, agent, is_checkpoint, status, prompt,
        decision_type, timeout_ms, model, next_node, on_approve, on_reject,
        on_timeout, on_true, on_false, on_pass, on_fail, on_error,
        on_failure, default_next, loop_body, branches, orchestration_mode,
        max_iterations, continue_condition, wait_all, action, input_mapping,
        output_mapping, transformer, rules, checks, steps, outputs,
        subflow_id, version, retry, ...rest }) => rest)(n as Record<string, unknown>),
    } as BuilderNodeData,
  }));

  // Derive edges from connection fields
  const rfEdges: Edge[] = [];
  let edgeIdx = 0;

  function addEdgeFromCkp(source: string, target: unknown, label: string) {
    if (typeof target !== "string" || !target) return;
    const id = `e${edgeIdx++}`;
    const col = edgeColor(label);
    rfEdges.push({
      id,
      source,
      target,
      label: label || undefined,
      type: "bezier",
      style: { stroke: col, strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: col },
      labelStyle: { fontSize: 10, fontWeight: 700, fill: col },
      labelBgStyle: { fill: "#fff", fillOpacity: 0.94 },
      labelBgPadding: [5, 3] as [number, number],
      labelBgBorderRadius: 4,
    });
  }

  for (const [id, n] of Object.entries(rawNodes)) {
    if (n.next_node)    addEdgeFromCkp(id, n.next_node,    "");
    if (n.on_approve)   addEdgeFromCkp(id, n.on_approve,   "approve");
    if (n.on_reject)    addEdgeFromCkp(id, n.on_reject,    "reject");
    if (n.on_timeout)   addEdgeFromCkp(id, n.on_timeout,   "timeout");
    if (n.on_true)      addEdgeFromCkp(id, n.on_true,      "true");
    if (n.on_false)     addEdgeFromCkp(id, n.on_false,     "false");
    if (n.on_pass)      addEdgeFromCkp(id, n.on_pass,      "pass");
    if (n.on_fail)      addEdgeFromCkp(id, n.on_fail,      "fail");
    if (n.on_error)     addEdgeFromCkp(id, n.on_error,     "error");
    if (n.on_failure)   addEdgeFromCkp(id, n.on_failure,   "error");
    if (n.default_next) addEdgeFromCkp(id, n.default_next, "default");
    if (n.loop_body)    addEdgeFromCkp(id, n.loop_body,    "loop body");
    // parallel branches
    if (Array.isArray(n.branches)) {
      for (const b of n.branches as Array<{ name?: string; entry_node?: string }>) {
        if (b.entry_node) addEdgeFromCkp(id, b.entry_node, b.name ? `branch:${b.name}` : "branch");
      }
    }
    // logic rules
    if (Array.isArray(n.rules)) {
      for (const r of n.rules as Array<{ next_node?: string; condition?: string }>) {
        if (r.next_node) addEdgeFromCkp(id, r.next_node, r.condition ?? "true");
      }
    }
  }

  // Auto layout
  const positions = dagreLayout(rfNodeList, rfEdges);
  for (const n of rfNodeList) {
    n.position = positions.get(n.id) ?? { x: 0, y: 0 };
  }

  return { nodes: rfNodeList, edges: rfEdges };
}

// ─── CKP export helpers ──────────────────────────────────────────────────────

function rfToCkp(
  nodes: Node<BuilderNodeData>[],
  edges: Edge[],
): Record<string, unknown> {
  const startNode = nodes.find((n) => (n.data as BuilderNodeData).isStart)?.id ?? nodes[0]?.id ?? "";

  const ckpNodes: Record<string, Record<string, unknown>> = {};

  for (const n of nodes) {
    const d = n.data as BuilderNodeData;
    const nodeId = n.id;

    // Outgoing edges for this node
    const outEdges = edges.filter((e) => e.source === nodeId);

    const obj: Record<string, unknown> = {
      type: d.nodeType,
      ...(d.description ? { description: d.description } : {}),
      ...(d.agent       ? { agent: d.agent }             : {}),
      ...(d.isCheckpoint ? { is_checkpoint: true }       : {}),
      ...(d.extra ?? {}),
    };

    // Reconstruct connection keys from outgoing edges
    for (const e of outEdges) {
      const label = (e.label as string | undefined) ?? "";
      const target = e.target;
      switch (label) {
        case "":
        case "next":       obj.next_node    = target; break;
        case "approve":    obj.on_approve   = target; break;
        case "reject":     obj.on_reject    = target; break;
        case "timeout":    obj.on_timeout   = target; break;
        case "true":       obj.on_true      = target; break;
        case "false":      obj.on_false     = target; break;
        case "pass":       obj.on_pass      = target; break;
        case "fail":       obj.on_fail      = target; break;
        case "error":      obj.on_error     = target; break;
        case "default":    obj.default_next = target; break;
        case "loop body":  obj.loop_body    = target; break;
        default: {
          // Reconstruct parallel branches array from "branch:" prefixed labels
          if (label.startsWith("branch:") || label === "branch") {
            if (!obj.branches) obj.branches = [];
            const branchName = label === "branch" ? undefined : label.slice(7);
            (obj.branches as Array<{ name?: string; entry_node: string }>).push({
              ...(branchName ? { name: branchName } : {}),
              entry_node: target,
            });
          } else {
            // custom label — store as a note
            if (!obj._custom_edges) obj._custom_edges = {};
            (obj._custom_edges as Record<string, string>)[label] = target;
          }
        }
      }
    }

    // Type-specific simple fields
    if (d.nodeType === "terminate" && d.status) obj.status = d.status;
    if (d.nodeType === "terminate" && d.outputs && Object.keys(d.outputs).length > 0) obj.outputs = d.outputs;
    // steps for sequence / WEB agent nodes
    if (d.steps && d.steps.length > 0) obj.steps = d.steps;
    if (d.nodeType === "human_approval") {
      if (d.approvalPrompt) obj.prompt        = d.approvalPrompt;
      if (d.decisionType)   obj.decision_type = d.decisionType;
      if (d.timeoutMs)      obj.timeout_ms    = d.timeoutMs;
    }
    if (d.nodeType === "llm_action") {
      if (d.llmPrompt) obj.prompt = d.llmPrompt;
      if (d.llmModel)  obj.model  = d.llmModel;
      if (d.orchestrationMode) {
        obj.orchestration_mode = true;
        const rawBranches = (d.orchestrationBranches ?? "").trim();
        obj.branches = rawBranches
          ? rawBranches.split(",").map((b) => b.trim()).filter(Boolean)
          : [];
      }
    }
    if (d.nodeType === "loop") {
      if (d.loopMaxIterations != null) obj.max_iterations = d.loopMaxIterations;
      if (d.loopContinueCondition)     obj.continue_condition = d.loopContinueCondition;
    }
    if (d.nodeType === "parallel") {
      if (d.parallelWaitAll != null) obj.wait_all = d.parallelWaitAll;
    }
    if (d.nodeType === "processing") {
      if (d.action) obj.action = d.action;
      if (d.inputMapping)  { try { obj.input_mapping  = JSON.parse(d.inputMapping);  } catch { obj.input_mapping  = d.inputMapping;  } }
      if (d.outputMapping) { try { obj.output_mapping = JSON.parse(d.outputMapping); } catch { obj.output_mapping = d.outputMapping; } }
    }
    if (d.nodeType === "transform") {
      if (d.transformer)   obj.transformer = d.transformer;
      if (d.inputMapping)  { try { obj.input_mapping  = JSON.parse(d.inputMapping);  } catch { obj.input_mapping  = d.inputMapping;  } }
      if (d.outputMapping) { try { obj.output_mapping = JSON.parse(d.outputMapping); } catch { obj.output_mapping = d.outputMapping; } }
    }
    if (d.nodeType === "verification") {
      if (d.checks && d.checks.length > 0) obj.checks = d.checks;
      if (d.verificationRules) { try { obj.rules = JSON.parse(d.verificationRules); } catch { obj.rules = d.verificationRules; } }
    }
    if (d.nodeType === "subflow") {
      if (d.subflowId)      obj.subflow_id = d.subflowId;
      if (d.subflowVersion) obj.version    = d.subflowVersion;
    }
    // universal failure / retry
    if (d.onFailureNode) obj.on_failure = d.onFailureNode;
    if (d.retryMaxAttempts) {
      obj.retry = {
        max_attempts: d.retryMaxAttempts,
        ...(d.retryBackoffMs ? { backoff_ms: d.retryBackoffMs } : {}),
      };
    }
    // extra JSON override (merged last so it can override anything above)
    if (d.extraJsonText) {
      try { Object.assign(obj, JSON.parse(d.extraJsonText)); } catch { /* ignore malformed JSON */ }
    }

    ckpNodes[nodeId] = obj;
  }

  return { start_node: startNode, nodes: ckpNodes };
}

// ─── Inspector panel ─────────────────────────────────────────────────────────

function NodeInspector({
  node,
  nodes,
  onUpdate,
  onSetStart,
  onDelete,
}: {
  node: Node<BuilderNodeData>;
  nodes: Node<BuilderNodeData>[];
  onUpdate: (id: string, patch: Partial<BuilderNodeData>) => void;
  onSetStart: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const d = node.data as BuilderNodeData;
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());
  const [expandedChecks, setExpandedChecks] = useState<Set<number>>(new Set());

  const toggleStep = (i: number) => setExpandedSteps((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  const toggleCheck = (i: number) => setExpandedChecks((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });

  const updateStep = (i: number, patch: Record<string, unknown>) => {
    const steps = [...(d.steps ?? [])];
    steps[i] = { ...steps[i], ...patch };
    onUpdate(node.id, { steps });
  };
  const addStep = () => {
    const steps = [...(d.steps ?? []), { step_id: `step_${(d.steps ?? []).length + 1}`, action: "navigate" }];
    onUpdate(node.id, { steps });
    setExpandedSteps((s) => new Set([...s, steps.length - 1]));
  };
  const removeStep = (i: number) => {
    const steps = (d.steps ?? []).filter((_, idx) => idx !== i);
    onUpdate(node.id, { steps });
  };
  const moveStep = (i: number, dir: -1 | 1) => {
    const steps = [...(d.steps ?? [])];
    const j = i + dir;
    if (j < 0 || j >= steps.length) return;
    [steps[i], steps[j]] = [steps[j], steps[i]];
    onUpdate(node.id, { steps });
  };

  const updateCheck = (i: number, patch: Record<string, unknown>) => {
    const checks = [...(d.checks ?? [])];
    checks[i] = { ...checks[i], ...patch };
    onUpdate(node.id, { checks });
  };
  const addCheck = () => {
    const checks = [...(d.checks ?? []), { id: `check_${(d.checks ?? []).length + 1}`, condition: "", on_fail: "fail_workflow", message: "" }];
    onUpdate(node.id, { checks });
    setExpandedChecks((s) => new Set([...s, checks.length - 1]));
  };
  const removeCheck = (i: number) => {
    const checks = (d.checks ?? []).filter((_, idx) => idx !== i);
    onUpdate(node.id, { checks });
  };

  const Field = ({
    label,
    children,
  }: {
    label: string;
    children: React.ReactNode;
  }) => (
    <div>
      <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-widest text-gray-400">
        {label}
      </label>
      {children}
    </div>
  );

  const inputCls =
    "w-full rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm focus:outline-none focus:border-indigo-400";

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold text-gray-700">Node Inspector</span>
        <button
          onClick={() => onDelete(node.id)}
          className="rounded px-1.5 py-0.5 text-[11px] text-red-600 hover:bg-red-50"
        >
          Delete
        </button>
      </div>

      <Field label="Node ID">
        <input
          className={inputCls}
          value={d.label}
          onChange={(e) => onUpdate(node.id, { label: e.target.value })}
          placeholder="e.g. init_step"
        />
        <p className="mt-0.5 text-[10px] text-gray-400">
          This becomes the CKP node key. Used in edge connections.
        </p>
      </Field>

      <Field label="Type">
        <select
          aria-label="Node type"
          className={inputCls}
          value={d.nodeType}
          onChange={(e) => onUpdate(node.id, { nodeType: e.target.value })}
        >
          {NODE_TYPES_LIST.map((t) => (
            <option key={t} value={t}>
              {TYPE_ICONS[t]} {t.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Description">
        <textarea
          className={`${inputCls} resize-none`}
          rows={2}
          value={d.description}
          onChange={(e) => onUpdate(node.id, { description: e.target.value })}
          placeholder="Optional description"
        />
      </Field>

      <Field label="Agent">
        <input
          className={inputCls}
          value={d.agent}
          onChange={(e) => onUpdate(node.id, { agent: e.target.value })}
          placeholder="e.g. WebAgent"
        />
      </Field>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="chk-ckpt"
          className="h-3.5 w-3.5 accent-indigo-600"
          checked={d.isCheckpoint}
          onChange={(e) => onUpdate(node.id, { isCheckpoint: e.target.checked })}
        />
        <label htmlFor="chk-ckpt" className="cursor-pointer text-xs text-gray-600">
          is_checkpoint
        </label>
      </div>

      {/* ── Steps editor (sequence nodes with WEB/agent steps) ── */}
      {(d.nodeType === "sequence") && (
        <div className="rounded-lg border border-blue-100 bg-blue-50/40 p-2 space-y-1.5">
          <div className="flex items-center justify-between">
            <p className="text-[9px] font-bold uppercase tracking-widest text-blue-500">Steps ({(d.steps ?? []).length})</p>
            <button onClick={addStep} className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700 hover:bg-blue-200">+ Add</button>
          </div>
          {(d.steps ?? []).length === 0 && (
            <p className="text-[10px] text-gray-400 italic">No steps yet. Click + Add to create one.</p>
          )}
          {(d.steps ?? []).map((step, idx) => {
            const expanded = expandedSteps.has(idx);
            const { step_id, action, ...rest } = step as Record<string, unknown>;
            return (
              <div key={idx} className="rounded-lg border border-blue-100 bg-white shadow-sm">
                {/* Collapsed header */}
                <div className="flex items-center gap-1 px-2 py-1.5">
                  <div className="flex shrink-0 flex-col gap-0.5">
                    <button onClick={() => moveStep(idx, -1)} disabled={idx === 0} className="text-gray-300 hover:text-gray-500 disabled:opacity-20 text-[9px] leading-none">▲</button>
                    <button onClick={() => moveStep(idx, 1)} disabled={idx === (d.steps ?? []).length - 1} className="text-gray-300 hover:text-gray-500 disabled:opacity-20 text-[9px] leading-none">▼</button>
                  </div>
                  <span className="shrink-0 rounded bg-blue-100 px-1 text-[9px] font-bold text-blue-500 min-w-[18px] text-center">{idx + 1}</span>
                  <button onClick={() => toggleStep(idx)} className="min-w-0 flex-1 text-left">
                    <span className="block truncate text-[11px] font-semibold text-gray-700">{(step_id as string) || "(unnamed)"}</span>
                    <span className="block truncate text-[9px] text-gray-400">{(action as string) || "—"}</span>
                  </button>
                  <button onClick={() => toggleStep(idx)} className="shrink-0 text-[9px] text-gray-400 hover:text-gray-600">{expanded ? "▲" : "▼"}</button>
                  <button onClick={() => removeStep(idx)} className="shrink-0 text-[9px] text-red-400 hover:text-red-600 px-0.5" title="Remove step">✕</button>
                </div>
                {/* Expanded fields */}
                {expanded && (
                  <div className="border-t border-blue-50 px-2 pb-2 pt-1.5 space-y-1.5">
                    <div className="flex gap-1.5">
                      <div className="flex-1">
                        <label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">step_id</label>
                        <input className={inputCls + " text-xs"} value={(step_id as string) ?? ""} onChange={(e) => updateStep(idx, { step_id: e.target.value })} placeholder="step_1" />
                      </div>
                      <div className="flex-1">
                        <label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">action</label>
                        <input className={inputCls + " text-xs"} value={(action as string) ?? ""} onChange={(e) => updateStep(idx, { action: e.target.value })} placeholder="navigate" list={`actions-${idx}`} />
                        <datalist id={`actions-${idx}`}>
                          {["navigate","click","fill","wait","wait_for_element","extract_text","select_all_text","screenshot","scroll","hover","select_option"].map((a) => <option key={a} value={a} />)}
                        </datalist>
                      </div>
                    </div>
                    {/* Action-specific quick fields */}
                    {(action === "navigate") && <div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">url</label><input className={inputCls + " text-xs"} value={(rest.url as string) ?? ""} onChange={(e) => updateStep(idx, { url: e.target.value })} placeholder="https://… or {{variable}}" /></div>}
                    {(action === "fill" || action === "click" || action === "wait_for_element" || action === "extract_text" || action === "select_all_text" || action === "hover" || action === "scroll") && <div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">target (selector)</label><input className={inputCls + " text-xs"} value={(rest.target as string) ?? ""} onChange={(e) => updateStep(idx, { target: e.target.value })} placeholder=".css-selector or #id" /></div>}
                    {(action === "fill") && <div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">value</label><input className={inputCls + " text-xs"} value={(rest.value as string) ?? ""} onChange={(e) => updateStep(idx, { value: e.target.value })} placeholder="text to type" /></div>}
                    {(action === "extract_text" || action === "select_all_text") && <div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">output_variable</label><input className={inputCls + " text-xs"} value={(rest.output_variable as string) ?? ""} onChange={(e) => updateStep(idx, { output_variable: e.target.value })} placeholder="my_var" /></div>}
                    {(action === "screenshot") && (<><div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">path</label><input className={inputCls + " text-xs"} value={(rest.path as string) ?? ""} onChange={(e) => updateStep(idx, { path: e.target.value })} placeholder="artifacts/{{run_id}}/shot.png" /></div><div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">output_variable</label><input className={inputCls + " text-xs"} value={(rest.output_variable as string) ?? ""} onChange={(e) => updateStep(idx, { output_variable: e.target.value })} /></div></>)}
                    {(action === "wait" || action === "wait_for_element") && <div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">timeout_ms</label><input type="number" className={inputCls + " text-xs"} value={(rest.timeout_ms as number) ?? ""} onChange={(e) => updateStep(idx, { timeout_ms: e.target.value ? Number(e.target.value) : undefined })} placeholder="15000" /></div>}
                    {/* Extra fields as JSON */}
                    {(() => {
                      const knownStepKeys = new Set(["step_id","action","url","target","value","output_variable","path","timeout_ms"]);
                      const extraRest = Object.fromEntries(Object.entries(rest).filter(([k]) => !knownStepKeys.has(k)));
                      return Object.keys(extraRest).length > 0 ? (
                        <div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">Other props</label><pre className="rounded bg-gray-50 p-1 text-[9px] text-gray-500 overflow-auto max-h-20">{JSON.stringify(extraRest, null, 2)}</pre></div>
                      ) : null;
                    })()}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Type-specific fields */}
      {d.nodeType === "terminate" && (
        <Field label="Status">
          <select
            aria-label="Terminate status"
            className={inputCls}
            value={d.status ?? "success"}
            onChange={(e) => onUpdate(node.id, { status: e.target.value })}
          >
            <option value="success">success</option>
            <option value="failed">failed</option>
            <option value="cancelled">cancelled</option>
          </select>
        </Field>
      )}

      {/* Terminate outputs */}
      {d.nodeType === "terminate" && (
        <Field label="Outputs (JSON object)">
          <textarea
            className={`${inputCls} resize-none font-mono text-[10px]`}
            rows={5}
            value={d.outputs ? JSON.stringify(d.outputs, null, 2) : ""}
            onChange={(e) => {
              try { onUpdate(node.id, { outputs: JSON.parse(e.target.value) }); }
              catch { onUpdate(node.id, { outputs: undefined }); }
            }}
            placeholder={'{ "result": "{{variable}}" }'}
          />
          <p className="mt-0.5 text-[10px] text-gray-400">Key → CKP variable reference map</p>
        </Field>
      )}

      {d.nodeType === "human_approval" && (
        <>
          <Field label="Approval Prompt">
            <textarea
              className={`${inputCls} resize-none`}
              rows={2}
              value={d.approvalPrompt ?? ""}
              onChange={(e) => onUpdate(node.id, { approvalPrompt: e.target.value })}
              placeholder="Decision prompt shown to approver"
            />
          </Field>
          <Field label="Decision Type">
            <select
              aria-label="Decision type"
              className={inputCls}
              value={d.decisionType ?? "approve_reject"}
              onChange={(e) => onUpdate(node.id, { decisionType: e.target.value })}
            >
              <option value="approve_reject">approve / reject</option>
              <option value="input">input required</option>
            </select>
          </Field>
          <Field label="Timeout (ms)">
            <input
              type="number"
              className={inputCls}
              value={d.timeoutMs ?? ""}
              onChange={(e) =>
                onUpdate(node.id, { timeoutMs: e.target.value ? Number(e.target.value) : undefined })
              }
              placeholder="e.g. 86400000"
            />
          </Field>
        </>
      )}

      {d.nodeType === "llm_action" && (
        <>
          <Field label="Prompt">
            <textarea
              className={`${inputCls} resize-none`}
              rows={3}
              value={d.llmPrompt ?? ""}
              onChange={(e) => onUpdate(node.id, { llmPrompt: e.target.value })}
              placeholder="LLM prompt template"
            />
          </Field>
          <Field label="Model">
            <input
              className={inputCls}
              value={d.llmModel ?? ""}
              onChange={(e) => onUpdate(node.id, { llmModel: e.target.value })}
              placeholder="e.g. gpt-4o"
            />
          </Field>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="chk-orch"
              className="h-3.5 w-3.5 accent-purple-600"
              checked={!!d.orchestrationMode}
              onChange={(e) => onUpdate(node.id, { orchestrationMode: e.target.checked })}
            />
            <label htmlFor="chk-orch" className="cursor-pointer text-xs font-semibold text-purple-700">
              🧠 orchestration_mode
            </label>
          </div>
          {d.orchestrationMode && (
            <Field label="Branches (comma-separated)">
              <input
                className={inputCls}
                value={d.orchestrationBranches ?? ""}
                onChange={(e) => onUpdate(node.id, { orchestrationBranches: e.target.value })}
                placeholder="e.g. path_a, path_b, escalate"
              />
              <p className="mt-0.5 text-[10px] text-purple-500">
                LLM must return JSON with <code>_next_node</code> set to one of these.
              </p>
            </Field>
          )}
        </>
      )}

      {d.extra && Object.keys(d.extra).length > 0 && (
        <div className="rounded-lg bg-gray-50 p-2">
          <p className="mb-1 text-[9px] font-bold uppercase tracking-widest text-gray-400">
            Extra CKP fields (passthrough)
          </p>
          <pre className="max-h-32 overflow-auto text-[10px] text-gray-500">
            {JSON.stringify(d.extra, null, 2)}
          </pre>
        </div>
      )}

      {/* ── Loop fields ── */}
      {d.nodeType === "loop" && (
        <>
          <Field label="Max Iterations">
            <input
              type="number"
              className={inputCls}
              value={d.loopMaxIterations ?? ""}
              onChange={(e) => onUpdate(node.id, { loopMaxIterations: e.target.value ? Number(e.target.value) : undefined })}
              placeholder="e.g. 10"
            />
          </Field>
          <Field label="Continue Condition">
            <input
              className={inputCls}
              value={d.loopContinueCondition ?? ""}
              onChange={(e) => onUpdate(node.id, { loopContinueCondition: e.target.value })}
              placeholder="e.g. $.counter < 5"
            />
            <p className="mt-0.5 text-[10px] text-gray-400">Expression that must be true to keep looping</p>
          </Field>
        </>
      )}

      {/* ── Parallel fields ── */}
      {d.nodeType === "parallel" && (
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="chk-waitall"
            className="h-3.5 w-3.5 accent-cyan-600"
            checked={d.parallelWaitAll ?? true}
            onChange={(e) => onUpdate(node.id, { parallelWaitAll: e.target.checked })}
          />
          <label htmlFor="chk-waitall" className="cursor-pointer text-xs text-gray-600">
            wait_all — wait for all branches before continuing
          </label>
        </div>
      )}

      {/* ── Logic / conditional fields ── */}
      {d.nodeType === "logic" && (
        <Field label="Default Next Node">
          <input
            className={inputCls}
            value={d.logicDefaultNext ?? ""}
            onChange={(e) => onUpdate(node.id, { logicDefaultNext: e.target.value })}
            placeholder="fallback node if no rule matches"
          />
          <p className="mt-0.5 text-[10px] text-gray-400">Routing via edge labels: true / false / custom condition</p>
        </Field>
      )}

      {/* ── Processing fields ── */}
      {d.nodeType === "processing" && (
        <>
          <Field label="Action (callable)">
            <input
              className={inputCls}
              value={d.action ?? ""}
              onChange={(e) => onUpdate(node.id, { action: e.target.value })}
              placeholder="e.g. my_module.process_data"
            />
          </Field>
          <Field label="Input Mapping (JSON)">
            <textarea
              className={`${inputCls} resize-none font-mono text-[10px]`}
              rows={3}
              value={d.inputMapping ?? ""}
              onChange={(e) => onUpdate(node.id, { inputMapping: e.target.value })}
              placeholder={'{"param": "$.output.value"}'}
            />
          </Field>
          <Field label="Output Mapping (JSON)">
            <textarea
              className={`${inputCls} resize-none font-mono text-[10px]`}
              rows={3}
              value={d.outputMapping ?? ""}
              onChange={(e) => onUpdate(node.id, { outputMapping: e.target.value })}
              placeholder={'{"result": "$.result"}'}
            />
          </Field>
        </>
      )}

      {/* ── Transform fields ── */}
      {d.nodeType === "transform" && (
        <>
          <Field label="Transformer">
            <input
              className={inputCls}
              value={d.transformer ?? ""}
              onChange={(e) => onUpdate(node.id, { transformer: e.target.value })}
              placeholder="e.g. jmespath or custom.transform_fn"
            />
          </Field>
          <Field label="Input Mapping (JSON)">
            <textarea
              className={`${inputCls} resize-none font-mono text-[10px]`}
              rows={3}
              value={d.inputMapping ?? ""}
              onChange={(e) => onUpdate(node.id, { inputMapping: e.target.value })}
              placeholder={'{"field": "$.source.value"}'}
            />
          </Field>
          <Field label="Output Mapping (JSON)">
            <textarea
              className={`${inputCls} resize-none font-mono text-[10px]`}
              rows={3}
              value={d.outputMapping ?? ""}
              onChange={(e) => onUpdate(node.id, { outputMapping: e.target.value })}
              placeholder={'{"out": "$.result"}'}
            />
          </Field>
        </>
      )}

      {/* ── Verification checks editor ── */}
      {d.nodeType === "verification" && (
        <div className="rounded-lg border border-amber-100 bg-amber-50/40 p-2 space-y-1.5">
          <div className="flex items-center justify-between">
            <p className="text-[9px] font-bold uppercase tracking-widest text-amber-500">Checks ({(d.checks ?? []).length})</p>
            <button onClick={addCheck} className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 hover:bg-amber-200">+ Add</button>
          </div>
          {(d.checks ?? []).length === 0 && (
            <p className="text-[10px] text-gray-400 italic">No checks yet.</p>
          )}
          {(d.checks ?? []).map((chk, idx) => {
            const expanded = expandedChecks.has(idx);
            const c = chk as Record<string, unknown>;
            return (
              <div key={idx} className="rounded-lg border border-amber-100 bg-white shadow-sm">
                <div className="flex items-center gap-1.5 px-2 py-1.5">
                  <span className="shrink-0 rounded bg-amber-100 px-1 text-[9px] font-bold text-amber-600">{idx + 1}</span>
                  <button onClick={() => toggleCheck(idx)} className="min-w-0 flex-1 text-left">
                    <span className="block truncate text-[11px] font-semibold text-gray-700">{(c.id as string) || "(unnamed)"}</span>
                    <span className="block truncate text-[9px] text-gray-400">{(c.condition as string) || "—"}</span>
                  </button>
                  <button onClick={() => toggleCheck(idx)} className="shrink-0 text-[9px] text-gray-400">{expanded ? "▲" : "▼"}</button>
                  <button onClick={() => removeCheck(idx)} className="shrink-0 text-[9px] text-red-400 hover:text-red-600 px-0.5">✕</button>
                </div>
                {expanded && (
                  <div className="border-t border-amber-50 px-2 pb-2 pt-1.5 space-y-1.5">
                    <div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">id</label><input className={inputCls + " text-xs"} value={(c.id as string) ?? ""} onChange={(e) => updateCheck(idx, { id: e.target.value })} placeholder="titles_found" /></div>
                    <div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">condition</label><input className={inputCls + " text-xs"} value={(c.condition as string) ?? ""} onChange={(e) => updateCheck(idx, { condition: e.target.value })} placeholder="{{variable}} > 0" /></div>
                    <div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">on_fail → node</label><input className={inputCls + " text-xs"} value={(c.on_fail as string) ?? ""} onChange={(e) => updateCheck(idx, { on_fail: e.target.value })} placeholder="fail_workflow" /></div>
                    <div><label className="mb-0.5 block text-[9px] font-bold uppercase tracking-widest text-gray-400">message</label><input className={inputCls + " text-xs"} value={(c.message as string) ?? ""} onChange={(e) => updateCheck(idx, { message: e.target.value })} placeholder="Human-readable failure reason" /></div>
                  </div>
                )}
              </div>
            );
          })}
          <Field label="Rules (JSON — legacy)">
            <textarea
              className={`${inputCls} resize-none font-mono text-[10px]`}
              rows={3}
              value={d.verificationRules ?? ""}
              onChange={(e) => onUpdate(node.id, { verificationRules: e.target.value })}
              placeholder={'[{"condition": "$.score > 0.9", "next_node": "pass_step"}]'}
            />
          </Field>
        </div>
      )}

      {/* ── Subflow fields ── */}
      {d.nodeType === "subflow" && (
        <>
          <Field label="Subflow ID">
            <input
              className={inputCls}
              value={d.subflowId ?? ""}
              onChange={(e) => onUpdate(node.id, { subflowId: e.target.value })}
              placeholder="e.g. approval_subflow"
            />
          </Field>
          <Field label="Version">
            <input
              className={inputCls}
              value={d.subflowVersion ?? ""}
              onChange={(e) => onUpdate(node.id, { subflowVersion: e.target.value })}
              placeholder="e.g. v1"
            />
          </Field>
        </>
      )}

      {/* ── Universal: Failure & Retry ── */}
      <div className="rounded-lg border border-orange-100 bg-orange-50/50 p-2 space-y-2">
        <p className="text-[9px] font-bold uppercase tracking-widest text-orange-400">Failure &amp; Retry</p>
        <Field label="On Failure → Node">
          <input
            className={inputCls}
            value={d.onFailureNode ?? ""}
            onChange={(e) => onUpdate(node.id, { onFailureNode: e.target.value })}
            placeholder="error_handler node id"
          />
        </Field>
        <div className="flex gap-2">
          <Field label="Max Retries">
            <input
              type="number"
              className={inputCls}
              value={d.retryMaxAttempts ?? ""}
              onChange={(e) => onUpdate(node.id, { retryMaxAttempts: e.target.value ? Number(e.target.value) : undefined })}
              placeholder="0"
            />
          </Field>
          <Field label="Backoff (ms)">
            <input
              type="number"
              className={inputCls}
              value={d.retryBackoffMs ?? ""}
              onChange={(e) => onUpdate(node.id, { retryBackoffMs: e.target.value ? Number(e.target.value) : undefined })}
              placeholder="1000"
            />
          </Field>
        </div>
      </div>

      {/* ── Editable extra JSON ── */}
      <Field label="Extra CKP Props (JSON)">
        <textarea
          className={`${inputCls} resize-none font-mono text-[10px]`}
          rows={3}
          value={d.extraJsonText ?? (d.extra && Object.keys(d.extra).length > 0 ? JSON.stringify(d.extra, null, 2) : "")}
          onChange={(e) => onUpdate(node.id, { extraJsonText: e.target.value })}
          placeholder='{"custom_key": "value"}'
        />
        <p className="mt-0.5 text-[10px] text-gray-400">Merged into the CKP node on save. Must be a valid JSON object.</p>
      </Field>

      <div className="mt-auto border-t border-gray-100 pt-3 space-y-2">
        {!d.isStart && (
          <button
            onClick={() => onSetStart(node.id)}
            className="w-full rounded-lg bg-emerald-50 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100"
          >
            ⬆ Set as Start Node
          </button>
        )}
        {d.isStart && (
          <div className="w-full rounded-lg bg-emerald-100 py-1.5 text-center text-xs font-bold text-emerald-700">
            ✓ This is the START node
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Edge inspector ───────────────────────────────────────────────────────────

function EdgeInspector({
  edge,
  onUpdate,
  onDelete,
}: {
  edge: Edge;
  onUpdate: (id: string, label: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="flex h-full flex-col gap-3 p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold text-gray-700">Edge Inspector</span>
        <button
          onClick={() => onDelete(edge.id)}
          className="rounded px-1.5 py-0.5 text-[11px] text-red-600 hover:bg-red-50"
        >
          Delete
        </button>
      </div>
      <div>
        <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-widest text-gray-400">
          Edge Label
        </label>
        <select
          aria-label="Edge label"
          className="w-full rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm focus:outline-none focus:border-indigo-400"
          value={(edge.label as string) ?? ""}
          onChange={(e) => onUpdate(edge.id, e.target.value)}
        >
          {EDGE_LABEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
          <option value="__custom">Custom…</option>
        </select>
      </div>
      <div className="text-[10px] text-gray-400">
        <p>
          <strong>{edge.source}</strong> → <strong>{edge.target}</strong>
        </p>
        <p className="mt-0.5">
          Label maps to the CKP connection key (e.g. "approve" → on_approve).
        </p>
      </div>
    </div>
  );
}

// ─── Node Palette ─────────────────────────────────────────────────────────────

function NodePalette({
  onAdd,
  onLoadTemplate,
}: {
  onAdd: (type: CkpNodeType) => void;
  onLoadTemplate: (tpl: WorkflowTemplate) => void;
}) {
  return (
    <div className="flex flex-col gap-0 p-2">
      <p className="mb-2 text-[9px] font-black uppercase tracking-widest text-gray-400 px-1">Add Node</p>

      {/* ── 3-tier category sections ── */}
      {NODE_PALETTE_GROUPS.map(({ category, types }) => {
        const meta = CATEGORY_META[category];
        return (
          <div key={category} className="mb-2">
            <div
              className="flex items-center gap-1.5 px-1.5 py-1 rounded-md mb-1"
              style={{ background: `${meta.color}15` }}
            >
              <div className="h-2 w-2 rounded-full shrink-0" style={{ background: meta.color }} />
              <span
                className="text-[9px] font-bold uppercase tracking-widest"
                style={{ color: meta.color }}
              >
                {meta.label}
              </span>
            </div>
            <div className="flex flex-col gap-1 pl-1">
              {types.map((t) => (
                <button
                  key={t}
                  onClick={() => onAdd(t)}
                  title={meta.description}
                  className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-left text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 transition-colors"
                  style={{ borderLeftColor: TYPE_BG[t], borderLeftWidth: 3 }}
                >
                  <span className="text-sm leading-none">{TYPE_ICONS[t]}</span>
                  <span className="capitalize text-[11px]">{t.replace(/_/g, " ")}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })}

      {/* ── Workflow templates ── */}
      <div className="mt-2 border-t border-gray-100 pt-2">
        <p className="mb-1.5 px-1 text-[9px] font-black uppercase tracking-widest text-gray-400">Templates</p>
        <div className="flex flex-col gap-1">
          {WORKFLOW_TEMPLATES.map((tpl) => (
            <button
              key={tpl.name}
              onClick={() => onLoadTemplate(tpl)}
              className="flex items-start gap-2 rounded-lg border border-gray-200 bg-gradient-to-r from-indigo-50 to-white px-2 py-1.5 text-left shadow-sm hover:border-indigo-300 hover:from-indigo-100 transition-colors"
            >
              <span className="text-base leading-none mt-0.5">{tpl.icon}</span>
              <div className="min-w-0">
                <p className="text-[11px] font-semibold text-gray-800 leading-tight">{tpl.name}</p>
                <p className="text-[9px] text-gray-400 leading-tight mt-0.5 line-clamp-2">{tpl.description}</p>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Main WorkflowBuilder ─────────────────────────────────────────────────────

interface WorkflowBuilderProps {
  /** Initial CKP workflow_graph JSON, or null for empty canvas */
  initialWorkflowGraph: Record<string, unknown> | null;
  /** Called with updated workflow_graph when user clicks Save */
  onSave: (workflowGraph: Record<string, unknown>) => void;
  /** Disables save (e.g. while async save in progress) */
  saving?: boolean;
}

export default function WorkflowBuilder({
  initialWorkflowGraph,
  onSave,
  saving = false,
}: WorkflowBuilderProps) {
  const [rfNodes, setRfNodes] = useState<Node<BuilderNodeData>[]>([]);
  const [rfEdges, setRfEdges] = useState<Edge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const nodeCounter = useRef(1);

  // Initialise from prop
  useEffect(() => {
    if (initialWorkflowGraph && Object.keys(initialWorkflowGraph).length > 0) {
      const { nodes, edges } = ckpToRf(initialWorkflowGraph);
      setRfNodes(nodes);
      setRfEdges(edges);
      nodeCounter.current = nodes.length + 1;
    }
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // ── Selection tracking ───────────────────────────────────────────────────
  const selectedNode = useMemo(
    () =>
      selectedNodeId
        ? (rfNodes.find((n) => n.id === selectedNodeId) as Node<BuilderNodeData> | undefined) ?? null
        : null,
    [selectedNodeId, rfNodes],
  );
  const selectedEdge = useMemo(
    () =>
      selectedEdgeId ? rfEdges.find((e) => e.id === selectedEdgeId) ?? null : null,
    [selectedEdgeId, rfEdges],
  );

  // ── RF change handlers ───────────────────────────────────────────────────
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setRfNodes((nds) => applyNodeChanges(changes, nds) as Node<BuilderNodeData>[]);
  }, []);

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setRfEdges((eds) => applyEdgeChanges(changes, eds));
  }, []);

  const onConnect = useCallback((params: Connection) => {
    const col = edgeColor("");
    setRfEdges((eds) =>
      addEdge(
        {
          ...params,
          type: "bezier",
          style: { stroke: col, strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: col },
          labelStyle: { fontSize: 10, fontWeight: 700, fill: col },
          labelBgStyle: { fill: "#fff", fillOpacity: 0.94 },
          labelBgPadding: [5, 3] as [number, number],
          labelBgBorderRadius: 4,
        },
        eds,
      ),
    );
  }, []);

  // ── Node selection via click ─────────────────────────────────────────────
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
    setSelectedEdgeId(null);
  }, []);

  const onEdgeClick = useCallback((_: React.MouseEvent, edge: Edge) => {
    setSelectedEdgeId(edge.id);
    setSelectedNodeId(null);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }, []);

  // ── Inspector callbacks ──────────────────────────────────────────────────
  const updateNode = useCallback(
    (id: string, patch: Partial<BuilderNodeData>) => {
      // When the user renames the Node ID (label), we also rename the
      // internal `.id` and update all edge source/target references.
      const isRename = patch.label !== undefined && patch.label !== id;
      const newId = isRename ? patch.label! : id;

      setRfNodes((nds) =>
        nds.map((n) =>
          n.id === id
            ? { ...n, id: newId, data: { ...n.data, ...patch } }
            : n,
        ) as Node<BuilderNodeData>[],
      );

      if (isRename) {
        setRfEdges((eds) =>
          eds.map((e) => ({
            ...e,
            source: e.source === id ? newId : e.source,
            target: e.target === id ? newId : e.target,
          })),
        );
        setSelectedNodeId(newId);
      }
    },
    [],
  );

  const setStartNode = useCallback((id: string) => {
    setRfNodes((nds) =>
      nds.map((n) => ({
        ...n,
        data: { ...n.data, isStart: n.id === id },
      })) as Node<BuilderNodeData>[],
    );
  }, []);

  const deleteNode = useCallback((id: string) => {
    setRfNodes((nds) => nds.filter((n) => n.id !== id));
    setRfEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
    setSelectedNodeId(null);
  }, []);

  const deleteEdge = useCallback((id: string) => {
    setRfEdges((eds) => eds.filter((e) => e.id !== id));
    setSelectedEdgeId(null);
  }, []);

  const updateEdgeLabel = useCallback((id: string, label: string) => {
    const col = edgeColor(label);
    setRfEdges((eds) =>
      eds.map((e) =>
        e.id === id
          ? {
              ...e,
              label: label || undefined,
              style: { stroke: col, strokeWidth: 2 },
              markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: col },
              labelStyle: { fontSize: 10, fontWeight: 700, fill: col },
            }
          : e,
      ),
    );
  }, []);

  // ── Add node from palette ────────────────────────────────────────────────
  const addNode = useCallback((type: CkpNodeType) => {
    const id = `${type}_${nodeCounter.current++}`;
    const isFirst = rfNodes.length === 0;
    const newNode: Node<BuilderNodeData> = {
      id,
      type: "builderNode",
      position: { x: 80 + Math.random() * 40, y: 80 + rfNodes.length * 140 },
      data: {
        label: id,
        nodeType: type,
        description: "",
        agent: "",
        isStart: isFirst,
        isCheckpoint: false,
        status: type === "terminate" ? "success" : undefined,
      } as BuilderNodeData,
    };
    setRfNodes((nds) => [...nds, newNode] as Node<BuilderNodeData>[]);
    setSelectedNodeId(id);
    setSelectedEdgeId(null);
  }, [rfNodes.length]);

  // ── Load workflow template ───────────────────────────────────────────────
  const loadTemplate = useCallback((tpl: WorkflowTemplate) => {
    const { nodes: tplNodes, edges: tplEdges } = ckpToRf(tpl.workflowGraph);
    setRfNodes(tplNodes);
    setRfEdges(tplEdges);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    nodeCounter.current = tplNodes.length + 1;
  }, []);

  // ── Auto-layout ──────────────────────────────────────────────────────────
  const autoLayout = useCallback(() => {
    const positions = dagreLayout(rfNodes, rfEdges);
    setRfNodes((nds) =>
      nds.map((n) => ({
        ...n,
        position: positions.get(n.id) ?? n.position,
      })) as Node<BuilderNodeData>[],
    );
  }, [rfNodes, rfEdges]);

  // ── Export ───────────────────────────────────────────────────────────────
  const handleSave = useCallback(() => {
    const wfGraph = rfToCkp(rfNodes, rfEdges);
    onSave(wfGraph);
  }, [rfNodes, rfEdges, onSave]);

  // ── Minimap node color ──────────────────────────────────────────────────
  const miniNodeColor = useCallback((node: Node) => {
    const d = node.data as BuilderNodeData;
    return TYPE_BG[d.nodeType ?? ""] ?? "#9CA3AF";
  }, []);

  const hasNodes = rfNodes.length > 0;

  return (
    <div className="flex h-[740px] w-full overflow-hidden rounded-xl border border-gray-200 shadow-sm">
      {/* ── Left: Palette ── */}
      <div className="w-52 shrink-0 overflow-y-auto border-r border-gray-200 bg-white">
        <NodePalette onAdd={addNode} onLoadTemplate={loadTemplate} />
      </div>

      {/* ── Center: Canvas ── */}
      <div className="flex flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex items-center gap-2 border-b border-gray-200 bg-white px-3 py-2">
          <button
            onClick={autoLayout}
            disabled={!hasNodes}
            className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40"
          >
            Auto Layout
          </button>
          <span className="text-xs text-gray-400">
            {rfNodes.length} node{rfNodes.length !== 1 ? "s" : ""} ·{" "}
            {rfEdges.length} edge{rfEdges.length !== 1 ? "s" : ""}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[10px] text-gray-400">
              Click a node/edge to inspect · Drag handle to connect · Del to delete
            </span>
            <button
              onClick={handleSave}
              disabled={saving || !hasNodes}
              className="rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save Workflow"}
            </button>
          </div>
        </div>

        {/* React Flow canvas */}
        <div className="flex-1">
          {/* Glow animation keyframe */}
          <style>{`
            @keyframes builder-enter {
              from { opacity: 0; transform: scale(0.95); }
              to   { opacity: 1; transform: scale(1); }
            }
          `}</style>
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            onPaneClick={onPaneClick}
            fitView
            fitViewOptions={{ padding: 0.18 }}
            minZoom={0.1}
            maxZoom={2.5}
            deleteKeyCode={["Backspace", "Delete"]}
            proOptions={{ hideAttribution: true }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={20}
              size={1}
              color="#D1D5DB"
            />
            <Controls
              position="bottom-right"
              className="!rounded-lg !border-gray-200 !bg-white !shadow-md"
            />
            <MiniMap
              nodeColor={miniNodeColor}
              maskColor="rgba(15,23,42,0.04)"
              className="!rounded-lg !border-gray-200 !bg-white !shadow-md"
              position="bottom-left"
              pannable
              zoomable
            />
            {!hasNodes && (
              <Panel position="top-center">
                <div className="rounded-xl border border-dashed border-gray-300 bg-white/90 px-6 py-4 text-center shadow-sm backdrop-blur-sm">
                  <p className="text-sm font-medium text-gray-500">
                    Empty canvas · Click a node type in the palette to get started
                  </p>
                </div>
              </Panel>
            )}
          </ReactFlow>
        </div>
      </div>

      {/* ── Right: Inspector ── */}
      <div className="w-80 shrink-0 overflow-y-auto border-l border-gray-200 bg-white">
        {selectedNode ? (
          <NodeInspector
            node={selectedNode}
            nodes={rfNodes}
            onUpdate={updateNode}
            onSetStart={setStartNode}
            onDelete={deleteNode}
          />
        ) : selectedEdge ? (
          <EdgeInspector
            edge={selectedEdge}
            onUpdate={updateEdgeLabel}
            onDelete={deleteEdge}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center">
            <span className="text-2xl">👆</span>
            <p className="text-xs text-gray-400">
              Click a node or edge to inspect and edit its properties.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
