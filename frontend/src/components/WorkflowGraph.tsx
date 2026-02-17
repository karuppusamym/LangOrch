"use client";

import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";

/* ── Type icons by CKP node type ────────────────────────────── */

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

/* ── Custom node component ──────────────────────────────────── */

interface CkpNodeData {
  label: string;
  nodeType: string;
  agent: string | null;
  color: string;
  isStart: boolean;
  [key: string]: unknown;
}

function CkpNode({ data }: NodeProps<Node<CkpNodeData>>) {
  const { label, nodeType, agent, color, isStart } = data;
  const icon = TYPE_ICONS[nodeType] ?? "●";

  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div
        className="rounded-lg border-2 bg-white px-4 py-3 shadow-md transition-shadow hover:shadow-lg"
        style={{
          borderColor: color,
          minWidth: 180,
          maxWidth: 260,
        }}
      >
        {/* Start badge */}
        {isStart && (
          <span className="absolute -top-2.5 left-2 rounded bg-green-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
            START
          </span>
        )}

        {/* Header */}
        <div className="flex items-center gap-2">
          <span
            className="flex h-7 w-7 items-center justify-center rounded-md text-sm text-white"
            style={{ backgroundColor: color }}
          >
            {icon}
          </span>
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            {nodeType.replace("_", " ")}
          </span>
        </div>

        {/* Label */}
        <p className="mt-1.5 text-sm font-medium leading-snug text-gray-800">
          {label}
        </p>

        {/* Agent badge */}
        {agent && (
          <span
            className="mt-2 inline-block rounded-full px-2 py-0.5 text-[10px] font-medium"
            style={{
              backgroundColor: `${color}18`,
              color: color,
            }}
          >
            {agent}
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400" />
    </>
  );
}

/* ── Main component ─────────────────────────────────────────── */

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
}

const nodeTypes = { ckpNode: CkpNode };

export default function WorkflowGraph({ graph }: WorkflowGraphProps) {
  // Convert backend graph data to React Flow format
  const rfNodes: Node<CkpNodeData>[] = useMemo(
    () =>
      graph.nodes.map((n) => ({
        id: n.id,
        type: "ckpNode",
        position: n.position,
        data: n.data,
      })),
    [graph.nodes]
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      graph.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label || undefined,
        animated: e.animated ?? false,
        style: { strokeWidth: 2 },
        labelStyle: { fontSize: 11, fontWeight: 500, fill: "#6B7280" },
        labelBgStyle: { fill: "#F9FAFB", fillOpacity: 0.9 },
        labelBgPadding: [4, 2] as [number, number],
      })),
    [graph.edges]
  );

  const nodeColor = useCallback(
    (node: Node) => {
      const data = node.data as CkpNodeData | undefined;
      return data?.color ?? "#9CA3AF";
    },
    []
  );

  return (
    <div className="h-[600px] w-full rounded-xl border border-gray-200 bg-white shadow-sm">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={2}
        defaultEdgeOptions={{
          type: "smoothstep",
        }}
      >
        <Background gap={16} size={1} color="#E5E7EB" />
        <Controls
          position="bottom-right"
          showInteractive={false}
          className="!rounded-lg !border-gray-200 !shadow-md"
        />
        <MiniMap
          nodeColor={nodeColor}
          maskColor="rgba(0,0,0,0.08)"
          className="!rounded-lg !border-gray-200 !shadow-md"
          position="bottom-left"
        />
      </ReactFlow>
    </div>
  );
}
