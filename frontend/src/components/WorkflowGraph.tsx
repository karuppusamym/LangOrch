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
  pending: "#9CA3AF",
};
const STATE_RING: Record<string, string> = {
  current: "0 0 0 0 rgba(59,130,246,0), 0 0 16px 4px rgba(59,130,246,0.45)",
  running: "0 0 0 0 rgba(59,130,246,0), 0 0 16px 4px rgba(59,130,246,0.45)",
  completed: "0 0 0 3px rgba(34,197,94,0.35)",
  failed: "0 0 0 3px rgba(239,68,68,0.45), 0 0 12px 2px rgba(239,68,68,0.3)",
  sla_breached: "0 0 0 3px rgba(249,115,22,0.45)",
  pending: "none",
};
const STATE_STATUS_ICON: Record<string, string> = {
  completed: "✓",
  failed: "✕",
  running: "◌",
  current: "◌",
  sla_breached: "!",
  pending: "⌛",
};
const STATE_LABEL_COLOR: Record<string, string> = {
  completed: "#16A34A",
  failed: "#DC2626",
  running: "#2563EB",
  current: "#2563EB",
  sla_breached: "#EA580C",
  pending: "#6B7280",
};

/* ── Edge styling by label keyword ──────────────────────────── */
function edgeStyle(label: string | undefined, animated: boolean) {
  const l = (label ?? "").toLowerCase();
  if (l === "approve" || l === "true" || l === "yes") return { stroke: "#22C55E", strokeWidth: 2.5 };
  if (l === "reject" || l === "false" || l === "no") return { stroke: "#EF4444", strokeWidth: 2.5 };
  if (l === "timeout" || l === "sla_breached") return { stroke: "#F97316", strokeWidth: 2, strokeDasharray: "6 3" };
  if (l === "default") return { stroke: "#9CA3AF", strokeWidth: 1.5, strokeDasharray: "4 3" };
  if (l.startsWith("branch:") || l === "loop body") return { stroke: "#8B5CF6", strokeWidth: 2 };
  if (animated) return { stroke: "#F59E0B", strokeWidth: 2.5 };
  return { stroke: "#6366F1", strokeWidth: 2 };
}

/* ── Dagre layout ────────────────────────────────────────────── */
const NODE_W = 244;
const NODE_H = 116;

function dagreLayout(
  nodes: Array<{ id: string }>,
  edges: Array<{ source: string; target: string }>,
): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 68, ranksep: 96, marginx: 36, marginy: 36 });
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
  isEnd?: boolean;
  description?: string;
  stepCount?: number;
  _execState?: string;
  _loopCount?: string;
  [key: string]: unknown;
}

function CkpNode({ data }: NodeProps<Node<CkpNodeData>>) {
  const { label, nodeType, agent, isStart, isEnd, description, stepCount, _execState: execState, _loopCount: loopCount } = data;
  const color = TYPE_BG[nodeType] ?? data.color ?? "#9CA3AF";
  const icon = TYPE_ICONS[nodeType] ?? "●";
  const borderColor = execState ? (STATE_BORDER[execState] ?? color) : color;
  const shadow = execState && STATE_RING[execState] !== "none" ? STATE_RING[execState] : "0 2px 8px rgba(0,0,0,0.07)";
  const isLive = execState === "current" || execState === "running";
  const isFailed = execState === "failed";
  const isPending = execState === "pending";

  return (
    <>
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-gray-300 !w-[9px] !h-[9px] !border-2 !border-white"
      />

      <div
        className={`relative rounded-xl border-2 bg-white transition-all duration-300 ${isPending ? "opacity-60 grayscale-[0.2]" : ""}`}
        style={{
          borderColor,
          boxShadow: shadow,
          width: NODE_W,
          minHeight: NODE_H,
          animation: isLive ? "glow-pulse 1.6s ease-in-out infinite" : undefined,
        }}
      >
        {/* Accent stripe */}
        <div className="h-[6px] w-full rounded-t-[10px]" style={{ background: color }} />

        <div className="px-3 pt-2 pb-3">
          {/* Header row */}
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
            <div className="flex items-center gap-1 shrink-0">
              {/* Step count badge */}
              {stepCount != null && stepCount > 0 && (
                <span className="rounded-full px-1.5 py-0.5 text-[9px] font-bold" style={{ background: `${color}18`, color }}>
                  {stepCount} step{stepCount !== 1 ? "s" : ""}
                </span>
              )}
              {/* Loop count badge */}
              {loopCount && (
                <span className="rounded-full px-1.5 py-0.5 text-[9px] font-bold whitespace-nowrap" style={{ background: `${color}18`, color }}>
                  ↻ {loopCount}
                </span>
              )}
              {/* Exec state badge */}
              {execState && (
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-black text-white${isLive ? " animate-spin" : ""}`}
                  style={{ background: STATE_BORDER[execState] ?? color, animationDuration: "2s" }}
                  title={execState}
                >
                  {STATE_STATUS_ICON[execState] ?? execState[0]}
                </span>
              )}
            </div>
          </div>

          {/* Label */}
          <p className={`mt-1.5 text-[13px] font-semibold leading-snug line-clamp-2 ${isFailed ? "text-red-700" : "text-gray-800"}`}>
            {label}
          </p>

          {/* Description */}
          {description && (
            <p className="mt-0.5 text-[10px] leading-tight text-gray-400 line-clamp-2">{description}</p>
          )}

          {/* Exec state label */}
          {execState && (
            <p className="mt-0.5 text-[9px] font-bold uppercase tracking-widest" style={{ color: STATE_LABEL_COLOR[execState] ?? color }}>
              {execState.replace(/_/g, " ")}
            </p>
          )}

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
        {/* END ribbon */}
        {(isEnd || nodeType === "terminate") && !isStart && (
          <span className="absolute -top-3 left-3 rounded-full bg-gray-500 px-2 py-0.5 text-[9px] font-black tracking-widest text-white shadow">
            END
          </span>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-gray-300 !w-[9px] !h-[9px] !border-2 !border-white"
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

export interface NodeStatus {
  state: "running" | "completed" | "failed" | "sla_breached" | "current" | "pending";
  loopCount?: string;
}

interface WorkflowGraphProps {
  graph: GraphData;
  nodeStates?: Record<string, NodeStatus>;
}

/* ── Legends ─────────────────────────────────────────────────── */
const EDGE_LEGEND = [
  { color: "#6366F1", label: "Flow" },
  { color: "#22C55E", label: "Approve / True" },
  { color: "#EF4444", label: "Reject / False" },
  { color: "#F59E0B", label: "Condition" },
  { color: "#F97316", label: "Timeout", dashed: true },
  { color: "#8B5CF6", label: "Loop / Branch" },
  { color: "#9CA3AF", label: "Default", dashed: true },
];

const EXEC_LEGEND = [
  { color: "#3B82F6", label: "In Progress", icon: "◌" },
  { color: "#22C55E", label: "Completed", icon: "✓" },
  { color: "#9CA3AF", label: "Pending", icon: "⌛" },
  { color: "#EF4444", label: "Failed", icon: "✕" },
  { color: "#F97316", label: "SLA breach", icon: "!" },
];

/* ── Main component ─────────────────────────────────────────── */
export default function WorkflowGraph({ graph, nodeStates }: WorkflowGraphProps) {
  const positions = useMemo(
    () => dagreLayout(graph.nodes, graph.edges),
    [graph.nodes, graph.edges],
  );

  const hasExecState = nodeStates && Object.keys(nodeStates).length > 0;

  const rfNodes: Node<CkpNodeData>[] = useMemo(
    () =>
      graph.nodes.map((n) => {
        const state = nodeStates?.[n.id];
        return {
          id: n.id,
          type: "ckpNode",
          position: positions.get(n.id) ?? n.position,
          data: {
            ...n.data,
            ...(state ? { _execState: state.state, _loopCount: state.loopCount } : { _execState: "pending" })
          },
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
          type: "bezier",
          style: { ...es },
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: es.stroke },
          labelStyle: { fontSize: 10, fontWeight: 700, fill: es.stroke },
          labelBgStyle: { fill: "#fff", fillOpacity: 0.94 },
          labelBgPadding: [5, 3] as [number, number],
          labelBgBorderRadius: 4,
        };
      }),
    [graph.edges],
  );

  const miniNodeColor = useCallback(
    (node: Node) => {
      const d = node.data as CkpNodeData;
      if (d._execState) return STATE_BORDER[d._execState] ?? "#9CA3AF";
      return TYPE_BG[d.nodeType ?? ""] ?? "#9CA3AF";
    },
    [],
  );

  return (
    <>
      {/* Glow-pulse keyframes for running nodes */}
      <style>{`
        @keyframes glow-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(59,130,246,0.45), 0 0 8px 2px rgba(59,130,246,0.2); }
          50%       { box-shadow: 0 0 0 4px rgba(59,130,246,0.15), 0 0 20px 6px rgba(59,130,246,0.4); }
        }
      `}</style>

      <div className="h-[700px] w-full overflow-hidden rounded-xl border border-gray-200 bg-slate-50 shadow-sm">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          minZoom={0.12}
          maxZoom={2.5}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Lines} gap={28} size={0.5} color="#E2E8F0" />

          <Controls
            position="bottom-right"
            showInteractive={false}
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

          {/* Top-right — node/edge counts */}
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

          {/* Top-left — edge legend + optional exec state legend */}
          <Panel position="top-left">
            <div className="flex flex-col gap-2">
              {/* Edge legend */}
              <div className="rounded-lg border border-gray-200 bg-white/95 px-3 py-2 shadow-sm backdrop-blur-sm">
                <p className="mb-1.5 text-[9px] font-black uppercase tracking-widest text-gray-400">Edge types</p>
                <div className="space-y-1">
                  {EDGE_LEGEND.map(({ color, label, dashed }) => (
                    <div key={label} className="flex items-center gap-2">
                      <svg width="20" height="8" viewBox="0 0 20 8">
                        <line x1="0" y1="4" x2="20" y2="4" stroke={color} strokeWidth="2"
                          strokeDasharray={dashed ? "4 2" : undefined} />
                        <polygon points="16,1 20,4 16,7" fill={color} />
                      </svg>
                      <span className="text-[10px] text-gray-600">{label}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Execution state legend — only when live on a run */}
              {hasExecState && (
                <div className="rounded-lg border border-gray-200 bg-white/95 px-3 py-2 shadow-sm backdrop-blur-sm">
                  <p className="mb-1.5 text-[9px] font-black uppercase tracking-widest text-gray-400">Exec state</p>
                  <div className="space-y-1">
                    {EXEC_LEGEND.map(({ color, label, icon }) => (
                      <div key={label} className="flex items-center gap-2">
                        <span className="flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-black text-white" style={{ background: color }}>
                          {icon}
                        </span>
                        <span className="text-[10px] text-gray-600">{label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Panel>
        </ReactFlow>
      </div>
    </>
  );
}
