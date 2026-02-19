"use client";

import { useCallback, useMemo } from "react";
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
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";

/* ── Node type icons ─────────────────────────────────────────── */

const TYPE_ICONS: Record<string, string> = {
  sequence: "▶",
  logic: "◇",
  loop: "↻",
  parallel: "⫽",
  human_approval: "✋",
  llm_action: "🤖",
  processing: "⚙",
  verification: "✓",
  transform: "⇌",
  subflow: "↗",
  terminate: "⏹",
};

/* ── Node type fill colors ───────────────────────────────────── */
const TYPE_BG: Record<string, string> = {
  sequence: "#3B82F6",
  logic: "#F59E0B",
  loop: "#8B5CF6",
  parallel: "#06B6D4",
  human_approval: "#EF4444",
  llm_action: "#10B981",
  processing: "#6366F1",
  verification: "#F97316",
  transform: "#EC4899",
  subflow: "#14B8A6",
  terminate: "#6B7280",
};

/* ── Execution state styling ─────────────────────────────────── */
const STATE_BORDER: Record<string, string> = {
  current: "#3B82F6",
  running: "#3B82F6",
  completed: "#22C55E",
  failed: "#EF4444",
  sla_breached: "#F97316",
};
const STATE_SHADOW: Record<string, string> = {
  current: "0 0 0 4px rgba(59,130,246,0.35)",
  running: "0 0 0 4px rgba(59,130,246,0.35)",
  completed: "0 0 0 3px rgba(34,197,94,0.3)",
  failed: "0 0 0 4px rgba(239,68,68,0.35)",
  sla_breached: "0 0 0 4px rgba(249,115,22,0.35)",
};
const STATE_STATUS_ICON: Record<string, string> = {
  completed: "✓",
  failed: "✕",
  running: "…",
  current: "…",
  sla_breached: "!",
};

/* ── Edge styling by label keyword ──────────────────────────── */
function edgeStyle(label: string | undefined, animated: boolean) {
  const l = (label ?? "").toLowerCase();
  if (l === "approve")                   return { stroke: "#22C55E" };
  if (l === "reject")                    return { stroke: "#EF4444" };
  if (l === "timeout" || l === "sla_breached")
                                         return { stroke: "#F97316", strokeDasharray: "5 3" };
  if (l === "default")                   return { stroke: "#9CA3AF", strokeDasharray: "4 3" };
  if (l.startsWith("branch:") || l === "loop body")
                                         return { stroke: "#8B5CF6" };
  if (animated)                          return { stroke: "#F59E0B" };
  return { stroke: "#6366F1" };
}

/* ── Dagre layout ────────────────────────────────────────────── */
const NODE_W = 224;
const NODE_H = 100;

function dagreLayout(
  nodes: Array<{ id: string }>,
  edges: Array<{ source: string; target: string }>,
): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 56, ranksep: 72, marginx: 24, marginy: 24 });
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

/* ── Custom node card ────────────────────────────────────────── */
interface CkpNodeData {
  label: string;
  nodeType: string;
  agent: string | null;
  color: string;
  isStart: boolean;
  _execState?: string;
  [key: string]: unknown;
}

function CkpNode({ data }: NodeProps<Node<CkpNodeData>>) {
  const { label, nodeType, agent, isStart, _execState: execState } = data;
  const color = TYPE_BG[nodeType] ?? data.color ?? "#9CA3AF";
  const icon  = TYPE_ICONS[nodeType] ?? "●";

  const borderColor = execState ? (STATE_BORDER[execState] ?? color) : color;
  const shadow      = execState ? (STATE_SHADOW[execState] ?? undefined) : undefined;
  const isPulsing   = execState === "current" || execState === "running";

  return (
    <>
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: "#D1D5DB", width: 8, height: 8, border: "2px solid #fff" }}
      />

      <div
        className={`relative rounded-xl border-2 bg-white transition-all duration-200 ${isPulsing ? "animate-pulse" : ""}`}
        style={{ borderColor, boxShadow: shadow, width: NODE_W, minHeight: NODE_H }}
      >
        {/* Accent stripe */}
        <div className="h-[5px] w-full rounded-t-[10px]" style={{ background: color }} />

        <div className="px-3 py-2 pb-3">
          {/* Header row */}
          <div className="flex items-center justify-between gap-1">
            <div className="flex items-center gap-1.5 min-w-0">
              <span
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-xs text-white"
                style={{ background: color }}
              >
                {icon}
              </span>
              <span className="truncate text-[10px] font-bold uppercase tracking-widest text-gray-400">
                {nodeType.replace(/_/g, " ")}
              </span>
            </div>
            {/* Exec state badge */}
            {execState && (
              <span
                className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-black text-white"
                style={{ background: STATE_BORDER[execState] ?? color }}
                title={execState}
              >
                {STATE_STATUS_ICON[execState] ?? execState[0]}
              </span>
            )}
          </div>

          {/* Label */}
          <p className="mt-1.5 text-[13px] font-semibold leading-snug text-gray-800 line-clamp-2">
            {label}
          </p>

          {/* Agent chip */}
          {agent && (
            <span
              className="mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: `${color}18`, color }}
            >
              🤖 {agent}
            </span>
          )}
        </div>

        {/* START ribbon */}
        {isStart && (
          <span className="absolute -top-3 left-3 rounded-full bg-emerald-500 px-2 py-0.5 text-[9px] font-black tracking-widest text-white shadow">
            START
          </span>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: "#D1D5DB", width: 8, height: 8, border: "2px solid #fff" }}
      />
    </>
  );
}

const nodeTypes = { ckpNode: CkpNode };

/* ── GraphData / Props types ─────────────────────────────────── */
interface GraphData {
  nodes: Array<{
    id: string;
    type: string;
    data: CkpNodeData;
    position: { x: number; y: number };
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    label?: string;
    animated?: boolean;
  }>;
}

interface WorkflowGraphProps {
  graph: GraphData;
  nodeStates?: Record<string, string>;
}

/* ── Legend row ──────────────────────────────────────────────── */
const EDGE_LEGEND = [
  { color: "#6366F1", label: "Flow" },
  { color: "#22C55E", label: "Approve" },
  { color: "#EF4444", label: "Reject" },
  { color: "#F59E0B", label: "Condition" },
  { color: "#F97316", label: "Timeout" },
  { color: "#8B5CF6", label: "Loop / Branch" },
  { color: "#9CA3AF", label: "Default" },
];

/* ── Main component ─────────────────────────────────────────── */
export default function WorkflowGraph({ graph, nodeStates }: WorkflowGraphProps) {
  // Compute dagre positions
  const positions = useMemo(
    () => dagreLayout(graph.nodes, graph.edges),
    [graph.nodes, graph.edges],
  );

  const rfNodes: Node<CkpNodeData>[] = useMemo(
    () =>
      graph.nodes.map((n) => {
        const state = nodeStates?.[n.id];
        return {
          id: n.id,
          type: "ckpNode",
          position: positions.get(n.id) ?? n.position,
          data: { ...n.data, ...(state ? { _execState: state } : {}) },
        };
      }),
    [graph.nodes, nodeStates, positions],
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      graph.edges.map((e) => {
        const animated = e.animated ?? false;
        const es = edgeStyle(e.label, animated);
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label || undefined,
          animated: e.label === "loop body" || animated,
          type: "smoothstep",
          style: { strokeWidth: 2, ...es },
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: es.stroke },
          labelStyle: { fontSize: 10, fontWeight: 700, fill: es.stroke },
          labelBgStyle: { fill: "#fff", fillOpacity: 0.92 },
          labelBgPadding: [4, 2] as [number, number],
          labelBgBorderRadius: 3,
        };
      }),
    [graph.edges],
  );

  const miniNodeColor = useCallback(
    (node: Node) => TYPE_BG[(node.data as CkpNodeData)?.nodeType ?? ""] ?? "#9CA3AF",
    [],
  );

  return (
    <div className="h-[660px] w-full overflow-hidden rounded-xl border border-gray-200 bg-slate-50 shadow-sm">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.15}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#CBD5E1" />

        <Controls
          position="bottom-right"
          showInteractive={false}
          className="!rounded-lg !border-gray-200 !bg-white !shadow-md"
        />

        <MiniMap
          nodeColor={miniNodeColor}
          maskColor="rgba(0,0,0,0.05)"
          className="!rounded-lg !border-gray-200 !bg-white !shadow-md"
          position="bottom-left"
          pannable
          zoomable
        />

        {/* Node / edge count */}
        <Panel position="top-right">
          <div className="flex gap-2 text-[10px] font-semibold text-gray-500">
            <span className="rounded-full border border-gray-200 bg-white px-2.5 py-1 shadow-sm">
              {graph.nodes.length} nodes
            </span>
            <span className="rounded-full border border-gray-200 bg-white px-2.5 py-1 shadow-sm">
              {graph.edges.length} edges
            </span>
          </div>
        </Panel>

        {/* Edge legend */}
        <Panel position="top-left">
          <div className="rounded-lg border border-gray-200 bg-white/95 px-3 py-2 shadow-sm backdrop-blur-sm">
            <p className="mb-1.5 text-[9px] font-black uppercase tracking-widest text-gray-500">
              Edge types
            </p>
            <div className="space-y-1">
              {EDGE_LEGEND.map(({ color, label }) => (
                <div key={label} className="flex items-center gap-2">
                  <span className="h-[2px] w-5 rounded-full" style={{ background: color }} />
                  <span className="text-[10px] text-gray-600">{label}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </ReactFlow>
    </div>
  );
}
