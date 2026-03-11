import dagre from "@dagrejs/dagre";
import { MarkerType, type Edge, type Node } from "@xyflow/react";

import type { BuilderNodeData } from "./types";

const NODE_W = 228;
const NODE_H = 124;

export function edgeColor(label: string | undefined) {
  const normalized = (label ?? "").toLowerCase();
  if (normalized === "approve" || normalized === "true" || normalized === "pass" || normalized === "yes") return "#22C55E";
  if (normalized === "reject" || normalized === "false" || normalized === "fail" || normalized === "no") return "#EF4444";
  if (normalized === "timeout" || normalized === "error") return "#F97316";
  if (normalized === "default") return "#9CA3AF";
  if (normalized === "loop body") return "#8B5CF6";
  return "#6366F1";
}

export function dagreLayout(
  nodes: Array<{ id: string }>,
  edges: Array<{ source: string; target: string }>,
): Map<string, { x: number; y: number }> {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: "TB", nodesep: 56, ranksep: 84, marginx: 24, marginy: 24 });

  for (const node of nodes) {
    graph.setNode(node.id, { width: NODE_W, height: NODE_H });
  }

  for (const edge of edges) {
    graph.setEdge(edge.source, edge.target);
  }

  dagre.layout(graph);

  const out = new Map<string, { x: number; y: number }>();
  for (const node of nodes) {
    const position = graph.node(node.id);
    if (position) {
      out.set(node.id, { x: position.x - NODE_W / 2, y: position.y - NODE_H / 2 });
    }
  }

  return out;
}

export function ckpToRf(
  workflowGraph: Record<string, unknown>,
): { nodes: Node<BuilderNodeData>[]; edges: Edge[] } {
  const startNode = (workflowGraph.start_node as string) ?? "";
  const rawNodes = (workflowGraph.nodes as Record<string, Record<string, unknown>>) ?? {};

  const rfNodeList: Node<BuilderNodeData>[] = Object.entries(rawNodes).map(([id, node]) => ({
    id,
    type: "builderNode",
    position: { x: 0, y: 0 },
    data: {
      label: id,
      nodeType: (node.type as BuilderNodeData["nodeType"]) ?? "sequence",
      description: (node.description as string) ?? "",
      agent: (node.agent as string) ?? "",
      isStart: id === startNode,
      isCheckpoint: !!(node.is_checkpoint as boolean),
      status: (node.status as string) ?? "",
      approvalPrompt: (node.prompt as string) ?? "",
      decisionType: (node.decision_type as string) ?? "",
      timeoutMs: node.timeout_ms as number | undefined,
      llmPrompt: (node.prompt as string) ?? "",
      llmModel: (node.model as string) ?? "",
      orchestrationMode: !!(node.orchestration_mode as boolean),
      orchestrationBranches: Array.isArray(node.branches)
        ? (node.branches as string[]).join(", ")
        : (node.branches as string) ?? "",
      loopMaxIterations: node.max_iterations as number | undefined,
      loopContinueCondition: (node.continue_condition as string) ?? "",
      parallelWaitAll: node.wait_all !== undefined ? !!(node.wait_all as boolean) : true,
      logicDefaultNext: (node.default_next as string) ?? "",
      action: (node.action as string) ?? "",
      inputMapping: node.input_mapping ? JSON.stringify(node.input_mapping, null, 2) : "",
      outputMapping: node.output_mapping ? JSON.stringify(node.output_mapping, null, 2) : "",
      transformer: (node.transformer as string) ?? "",
      verificationRules: Array.isArray(node.rules) || (node.rules && typeof node.rules === "object")
        ? JSON.stringify(node.rules, null, 2)
        : (node.rules as string) ?? "",
      subflowId: (node.subflow_id as string) ?? "",
      subflowVersion: (node.version as string) ?? "",
      steps: Array.isArray(node.steps) ? (node.steps as Record<string, unknown>[]) : [],
      checks: Array.isArray(node.checks) ? (node.checks as Record<string, unknown>[]) : [],
      outputs: (node.outputs && typeof node.outputs === "object" && !Array.isArray(node.outputs))
        ? (node.outputs as Record<string, unknown>)
        : undefined,
      onFailureNode: typeof node.on_failure === "string" ? node.on_failure : "",
      retryMaxAttempts: (node.retry as Record<string, unknown>)?.max_attempts as number | undefined,
      retryBackoffMs: (node.retry as Record<string, unknown>)?.backoff_ms as number | undefined,
      extra: (({
        type,
        description,
        agent,
        is_checkpoint,
        status,
        prompt,
        decision_type,
        timeout_ms,
        model,
        next_node,
        on_approve,
        on_reject,
        on_timeout,
        on_true,
        on_false,
        on_pass,
        on_fail,
        on_error,
        on_failure,
        default_next,
        loop_body,
        branches,
        orchestration_mode,
        max_iterations,
        continue_condition,
        wait_all,
        action,
        input_mapping,
        output_mapping,
        transformer,
        rules,
        checks,
        steps,
        outputs,
        subflow_id,
        version,
        retry,
        ...rest
      }) => rest)(node as Record<string, unknown>),
    },
  }));

  const rfEdges: Edge[] = [];
  let edgeIndex = 0;

  function addEdgeFromCkp(source: string, target: unknown, label: string) {
    if (typeof target !== "string" || !target) return;

    const color = edgeColor(label);
    rfEdges.push({
      id: `e${edgeIndex++}`,
      source,
      target,
      label: label || undefined,
      type: "default",
      style: { stroke: color, strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
      labelStyle: { fontSize: 10, fontWeight: 700, fill: color },
      labelBgStyle: { fill: "#fff", fillOpacity: 0.94 },
      labelBgPadding: [5, 3] as [number, number],
      labelBgBorderRadius: 4,
    });
  }

  for (const [id, node] of Object.entries(rawNodes)) {
    if (node.next_node) addEdgeFromCkp(id, node.next_node, "");
    if (node.on_approve) addEdgeFromCkp(id, node.on_approve, "approve");
    if (node.on_reject) addEdgeFromCkp(id, node.on_reject, "reject");
    if (node.on_timeout) addEdgeFromCkp(id, node.on_timeout, "timeout");
    if (node.on_true) addEdgeFromCkp(id, node.on_true, "true");
    if (node.on_false) addEdgeFromCkp(id, node.on_false, "false");
    if (node.on_pass) addEdgeFromCkp(id, node.on_pass, "pass");
    if (node.on_fail) addEdgeFromCkp(id, node.on_fail, "fail");
    if (node.on_error) addEdgeFromCkp(id, node.on_error, "error");
    if (node.on_failure) addEdgeFromCkp(id, node.on_failure, "error");
    if (node.default_next) addEdgeFromCkp(id, node.default_next, "default");
    if (node.loop_body) addEdgeFromCkp(id, node.loop_body, "loop body");

    if (Array.isArray(node.branches)) {
      for (const branch of node.branches as Array<{ name?: string; entry_node?: string }>) {
        if (branch.entry_node) addEdgeFromCkp(id, branch.entry_node, branch.name ? `branch:${branch.name}` : "branch");
      }
    }

    if (Array.isArray(node.rules)) {
      for (const rule of node.rules as Array<{ next_node?: string; condition?: string }>) {
        if (rule.next_node) addEdgeFromCkp(id, rule.next_node, rule.condition ?? "true");
      }
    }
  }

  const positions = dagreLayout(rfNodeList, rfEdges);
  for (const node of rfNodeList) {
    node.position = positions.get(node.id) ?? { x: 0, y: 0 };
  }

  return { nodes: rfNodeList, edges: rfEdges };
}

export function rfToCkp(
  nodes: Node<BuilderNodeData>[],
  edges: Edge[],
): Record<string, unknown> {
  const startNode = nodes.find((node) => node.data.isStart)?.id ?? nodes[0]?.id ?? "";
  const ckpNodes: Record<string, Record<string, unknown>> = {};

  for (const node of nodes) {
    const data = node.data;
    const nodeId = node.id;
    const outEdges = edges.filter((edge) => edge.source === nodeId);

    const obj: Record<string, unknown> = {
      type: data.nodeType,
      ...(data.description ? { description: data.description } : {}),
      ...(data.agent ? { agent: data.agent } : {}),
      ...(data.isCheckpoint ? { is_checkpoint: true } : {}),
      ...(data.extra ?? {}),
    };

    for (const edge of outEdges) {
      const label = (edge.label as string | undefined) ?? "";
      const target = edge.target;
      switch (label) {
        case "":
        case "next": obj.next_node = target; break;
        case "approve": obj.on_approve = target; break;
        case "reject": obj.on_reject = target; break;
        case "timeout": obj.on_timeout = target; break;
        case "true": obj.on_true = target; break;
        case "false": obj.on_false = target; break;
        case "pass": obj.on_pass = target; break;
        case "fail": obj.on_fail = target; break;
        case "error": obj.on_error = target; break;
        case "default": obj.default_next = target; break;
        case "loop body": obj.loop_body = target; break;
        default: {
          if (label.startsWith("branch:") || label === "branch") {
            if (!obj.branches) obj.branches = [];
            const branchName = label === "branch" ? undefined : label.slice(7);
            (obj.branches as Array<{ name?: string; entry_node: string }>).push({
              ...(branchName ? { name: branchName } : {}),
              entry_node: target,
            });
          } else {
            if (!obj._custom_edges) obj._custom_edges = {};
            (obj._custom_edges as Record<string, string>)[label] = target;
          }
        }
      }
    }

    if (data.nodeType === "terminate" && data.status) obj.status = data.status;
    if (data.nodeType === "terminate" && data.outputs && Object.keys(data.outputs).length > 0) obj.outputs = data.outputs;
    if (data.steps && data.steps.length > 0) obj.steps = data.steps;

    if (data.nodeType === "human_approval") {
      if (data.approvalPrompt) obj.prompt = data.approvalPrompt;
      if (data.decisionType) obj.decision_type = data.decisionType;
      if (data.timeoutMs) obj.timeout_ms = data.timeoutMs;
    }

    if (data.nodeType === "llm_action") {
      if (data.llmPrompt) obj.prompt = data.llmPrompt;
      if (data.llmModel) obj.model = data.llmModel;
      if (data.orchestrationMode) {
        obj.orchestration_mode = true;
        const rawBranches = (data.orchestrationBranches ?? "").trim();
        obj.branches = rawBranches ? rawBranches.split(",").map((branch) => branch.trim()).filter(Boolean) : [];
      }
    }

    if (data.nodeType === "loop") {
      if (data.loopMaxIterations != null) obj.max_iterations = data.loopMaxIterations;
      if (data.loopContinueCondition) obj.continue_condition = data.loopContinueCondition;
    }

    if (data.nodeType === "parallel") {
      if (data.parallelWaitAll != null) obj.wait_all = data.parallelWaitAll;
    }

    if (data.nodeType === "processing") {
      if (data.action) obj.action = data.action;
      if (data.inputMapping) {
        try { obj.input_mapping = JSON.parse(data.inputMapping); } catch { obj.input_mapping = data.inputMapping; }
      }
      if (data.outputMapping) {
        try { obj.output_mapping = JSON.parse(data.outputMapping); } catch { obj.output_mapping = data.outputMapping; }
      }
    }

    if (data.nodeType === "transform") {
      if (data.transformer) obj.transformer = data.transformer;
      if (data.inputMapping) {
        try { obj.input_mapping = JSON.parse(data.inputMapping); } catch { obj.input_mapping = data.inputMapping; }
      }
      if (data.outputMapping) {
        try { obj.output_mapping = JSON.parse(data.outputMapping); } catch { obj.output_mapping = data.outputMapping; }
      }
    }

    if (data.nodeType === "verification") {
      if (data.checks && data.checks.length > 0) obj.checks = data.checks;
      if (data.verificationRules) {
        try { obj.rules = JSON.parse(data.verificationRules); } catch { obj.rules = data.verificationRules; }
      }
    }

    if (data.nodeType === "subflow") {
      if (data.subflowId) obj.subflow_id = data.subflowId;
      if (data.subflowVersion) obj.version = data.subflowVersion;
    }

    if (data.onFailureNode) obj.on_failure = data.onFailureNode;
    if (data.retryMaxAttempts) {
      obj.retry = {
        max_attempts: data.retryMaxAttempts,
        ...(data.retryBackoffMs ? { backoff_ms: data.retryBackoffMs } : {}),
      };
    }

    if (data.extraJsonText) {
      try { Object.assign(obj, JSON.parse(data.extraJsonText)); } catch { }
    }

    ckpNodes[nodeId] = obj;
  }

  return { start_node: startNode, nodes: ckpNodes };
}