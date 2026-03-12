"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  applyNodeChanges,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";

import type { BuilderDraftDocument, BuilderNodeDraft, BuilderNodeKind } from "@/builder-v2/reference-contract";
import { edgeColor } from "@/builder-v2/legacy/transforms";
import { DEFAULT_NODE_THEME, TYPE_BG, TYPE_ICONS, TYPE_THEME } from "@/builder-v2/legacy/catalog";
import type { BuilderNodeExecutionState, BuilderRunOverlay } from "@/builder-v2/execution/run-overlay";

interface BuilderCanvasProps {
  draft: BuilderDraftDocument;
  selectedNodeId: string | null;
  runOverlay?: BuilderRunOverlay | null;
  fitViewToken?: number;
  issuesByNodeId?: Map<string, { errors: number; warnings: number }>;
  canvasSearchQuery?: string;
  onSelectNode: (nodeId: string | null) => void;
  onNodePositionPreview: (positions: Array<{ id: string; position: { x: number; y: number } }>) => void;
  onNodePositionCommit: (positions: Array<{ id: string; position: { x: number; y: number } }>) => void;
  onConnectTransition: (connection: Connection) => void;
  onDeleteNode?: (nodeId: string) => void;
  onSetStartNode?: (nodeId: string) => void;
  onDropNode?: (kind: BuilderNodeKind, position: { x: number; y: number }) => void;
  onDuplicateNode?: (nodeId: string) => void;
  onDeleteEdge?: (sourceNodeId: string, transitionKey: string) => void;
}

function mapNodePositions(nodes: Array<Node<CanvasNodeData>>) {
  return nodes.map((node) => ({ id: node.id, position: node.position }));
}

interface CanvasNodeData extends Record<string, unknown> {
  draftNode: BuilderNodeDraft;
  isStart: boolean;
  runState: BuilderNodeExecutionState;
  runStatus: string | null;
  loopCount?: string;
  issueCount: { errors: number; warnings: number };
  isHighlighted: boolean;
}

const CANVAS_NODE_WIDTH = 164;
const CANVAS_NODE_HEIGHT = 84;

function getRunStateClass(runState: BuilderNodeExecutionState, selected: boolean, fallbackBorder: string) {
  if (selected) {
    return "border-indigo-500 shadow-[0_0_0_3px_rgba(99,102,241,0.18)]";
  }
  if (runState === "current") {
    return "border-sky-400 shadow-[0_0_0_3px_rgba(14,165,233,0.16)]";
  }
  if (runState === "running") {
    return "border-cyan-300 shadow-[0_0_0_3px_rgba(34,211,238,0.12)]";
  }
  if (runState === "paused") {
    return "border-amber-300 shadow-[0_0_0_3px_rgba(245,158,11,0.14)]";
  }
  if (runState === "completed") {
    return "border-emerald-300 shadow-[0_0_0_3px_rgba(16,185,129,0.12)]";
  }
  if (runState === "failed") {
    return "border-rose-300 shadow-[0_0_0_3px_rgba(244,63,94,0.14)]";
  }
  if (runState === "sla_breached") {
    return "border-fuchsia-300 shadow-[0_0_0_3px_rgba(217,70,239,0.12)]";
  }
  return `${fallbackBorder} shadow-[0_4px_14px_rgba(0,0,0,0.06)]`;
}

function getRunBadge(runState: BuilderNodeExecutionState, runStatus: string | null) {
  if (runState === "current") {
    return { label: "Live", className: "bg-sky-100 text-sky-700" };
  }
  if (runState === "running") {
    return { label: "Running", className: "bg-cyan-100 text-cyan-700" };
  }
  if (runState === "paused") {
    return { label: runStatus === "waiting_approval" ? "Waiting" : "Paused", className: "bg-amber-100 text-amber-700" };
  }
  if (runState === "completed") {
    return { label: "Done", className: "bg-emerald-100 text-emerald-700" };
  }
  if (runState === "failed") {
    return { label: "Failed", className: "bg-rose-100 text-rose-700" };
  }
  if (runState === "sla_breached") {
    return { label: "SLA", className: "bg-fuchsia-100 text-fuchsia-700" };
  }
  return null;
}

function DraftNodeCard({ data, selected }: NodeProps<Node<CanvasNodeData>>) {
  const node = data.draftNode;
  const theme = TYPE_THEME[node.kind] ?? DEFAULT_NODE_THEME;
  const icon = TYPE_ICONS[node.kind] ?? "●";
  const runBadge = getRunBadge(data.runState, data.runStatus);
  const hasErrors = data.issueCount.errors > 0;
  const hasWarnings = data.issueCount.warnings > 0;

  return (
    <>
      <Handle
        type="target"
        position={Position.Top}
        className="!h-[10px] !w-[10px] !border-2 !border-white !bg-neutral-300"
      />
      <div
        className={`relative w-[164px] rounded-[18px] border-2 bg-white shadow-sm transition ${getRunStateClass(data.runState, selected, theme.border)}${data.isHighlighted ? " ring-2 ring-yellow-400 ring-offset-1" : ""}`}
      >
        {(hasErrors || hasWarnings) && (
          <div className="absolute -right-1.5 -top-1.5 z-10 flex gap-0.5">
            {hasErrors ? (
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[8px] font-bold text-white shadow">
                {data.issueCount.errors}
              </span>
            ) : null}
            {hasWarnings && !hasErrors ? (
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-amber-400 text-[8px] font-bold text-white shadow">
                {data.issueCount.warnings}
              </span>
            ) : null}
          </div>
        )}
        <div className={`h-1 rounded-t-[16px] ${theme.accent}`} />
        <div className="p-2">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[10px] text-white shadow-sm ${theme.iconBg}`}>
                  {icon}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[11px] font-semibold text-neutral-900">{node.title}</p>
                  <p className="truncate text-[8px] font-bold uppercase tracking-[0.14em] text-neutral-400">
                    {node.kind.replace(/_/g, " ")}
                  </p>
                </div>
              </div>
            </div>
            {data.isStart ? (
              <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.14em] text-emerald-700">
                Start
              </span>
            ) : null}
          </div>
          {runBadge ? (
            <div className="mt-1 flex flex-wrap items-center gap-1">
              <span className={`rounded-full px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.12em] ${runBadge.className}`}>
                {runBadge.label}
              </span>
              {data.runStatus ? (
                data.runState !== "completed" ? (
                  <span className="rounded-full bg-neutral-100 px-1.5 py-0.5 text-[8px] font-medium uppercase tracking-[0.12em] text-neutral-600">
                    {data.runStatus.replace(/_/g, " ")}
                  </span>
                ) : null
              ) : null}
              {data.loopCount ? (
                <span className="rounded-full bg-violet-100 px-1.5 py-0.5 text-[8px] font-medium uppercase tracking-[0.12em] text-violet-700">
                  loop {data.loopCount}
                </span>
              ) : null}
            </div>
          ) : null}
          <p className="mt-1 line-clamp-2 min-h-6 text-[9px] leading-4 text-neutral-500">
            {node.description || "No description yet."}
          </p>
          <div className="mt-1 border-t border-neutral-100 pt-1">
            <div className="flex flex-wrap gap-1">
            {node.agent ? (
              <span className="rounded-full bg-neutral-100 px-1.5 py-0.5 text-[8px] font-medium text-neutral-600">
                agent: {node.agent}
              </span>
            ) : null}
            {node.transitions.map((transition, index) => (
              index < 2 ? (
                <span
                  key={`${node.id}-${transition.key}`}
                  className={`rounded-full px-1.5 py-0.5 text-[8px] font-medium ${theme.tint} ${theme.text}`}
                >
                  {transition.key}
                </span>
              ) : null
            ))}
            {node.transitions.length > 2 ? (
              <span className="rounded-full bg-neutral-100 px-1.5 py-0.5 text-[8px] font-medium text-neutral-500">
                +{node.transitions.length - 2}
              </span>
            ) : null}
            </div>
          </div>
        </div>

        {node.transitions.length > 0 ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center gap-4 pb-[-2px]">
            {node.transitions.map((transition, index) => (
              <Handle
                key={`${node.id}-${transition.key}`}
                id={transition.key}
                type="source"
                position={Position.Bottom}
                style={{
                  left: `${((index + 1) / (node.transitions.length + 1)) * 100}%`,
                  background: TYPE_BG[node.kind] ?? "#9CA3AF",
                  width: 10,
                  height: 10,
                  border: "2px solid white",
                }}
                className="!pointer-events-auto"
              />
            ))}
          </div>
        ) : null}

      </div>
    </>
  );
}

const nodeTypes = { builderNode: DraftNodeCard };

function ContextMenuOverlay({
  nodeId,
  x,
  y,
  isStart,
  onSetStartNode,
  onDeleteNode,
  onDuplicateNode,
  onClose,
}: {
  nodeId: string;
  x: number;
  y: number;
  isStart: boolean;
  onSetStartNode?: (id: string) => void;
  onDeleteNode?: (id: string) => void;
  onDuplicateNode?: (id: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.style.setProperty("top", `${y}px`);
      ref.current.style.setProperty("left", `${x}px`);
    }
  }, [x, y]);

  return (
    <div
      ref={ref}
      role="menu"
      className="fixed z-50 min-w-[156px] overflow-hidden rounded-2xl border border-neutral-200 bg-white py-1 shadow-2xl"
    >
      <p className="truncate border-b border-neutral-100 px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-neutral-400">
        {nodeId}
      </p>
      {!isStart && onSetStartNode ? (
        <button
          type="button"
          role="menuitem"
          onClick={() => { onSetStartNode(nodeId); onClose(); }}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-neutral-700 hover:bg-neutral-50"
        >
          <span className="text-emerald-600">●</span> Set as Start Node
        </button>
      ) : null}
      {onDuplicateNode ? (
        <button
          type="button"
          role="menuitem"
          onClick={() => { onDuplicateNode(nodeId); onClose(); }}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-neutral-700 hover:bg-neutral-50"
        >
          <span className="text-indigo-500">⧉</span> Duplicate Node
        </button>
      ) : null}
      {onDeleteNode ? (
        <button
          type="button"
          role="menuitem"
          onClick={() => { onDeleteNode(nodeId); onClose(); }}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-600 hover:bg-red-50"
        >
          <span>✕</span> Delete Node
        </button>
      ) : null}
    </div>
  );
}

interface ContextMenu {
  nodeId: string;
  x: number;
  y: number;
  isStart: boolean;
}

export function BuilderCanvas({
  draft,
  selectedNodeId,
  runOverlay = null,
  fitViewToken = 0,
  issuesByNodeId,
  canvasSearchQuery = "",
  onSelectNode,
  onNodePositionPreview,
  onNodePositionCommit,
  onConnectTransition,
  onDeleteNode,
  onSetStartNode,
  onDropNode,
  onDuplicateNode,
  onDeleteEdge,
}: BuilderCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const hasInitializedViewportRef = useRef(false);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance<Node<CanvasNodeData>, Edge> | null>(null);
  const [zoomPercent, setZoomPercent] = useState(100);
  const [contextMenu, setContextMenu] = useState<ContextMenu | null>(null);

  const derivedNodes = useMemo<Node<CanvasNodeData>[]>(() => {
    const query = canvasSearchQuery.trim().toLowerCase();
    return draft.nodes.map((node) => ({
      id: node.id,
      type: "builderNode",
      position: node.position,
      selected: node.id === selectedNodeId,
      data: {
        draftNode: node,
        isStart: draft.startNodeId === node.id,
        runState: runOverlay?.nodeStates[node.id]?.state ?? "idle",
        runStatus: runOverlay?.nodeStates[node.id] ? runOverlay.status : null,
        loopCount: runOverlay?.nodeStates[node.id]?.loopCount,
        issueCount: issuesByNodeId?.get(node.id) ?? { errors: 0, warnings: 0 },
        isHighlighted: query.length > 0 && [node.id, node.title, node.kind, node.description ?? ""].some((v) =>
          v.toLowerCase().includes(query),
        ),
      },
    }));
  }, [draft.nodes, draft.startNodeId, runOverlay, selectedNodeId, issuesByNodeId, canvasSearchQuery]);
  const [canvasNodes, setCanvasNodes] = useState<Node<CanvasNodeData>[]>(derivedNodes);

  useEffect(() => {
    setCanvasNodes(derivedNodes);
  }, [derivedNodes]);

  const edges = useMemo<Edge[]>(() => (
    draft.nodes.flatMap((node) =>
      node.transitions
        .filter((transition) => transition.targetNodeId)
        .map((transition) => {
          const label = transition.key === "next" ? undefined : transition.key;
          const traversalCount = runOverlay?.edgeTraversals[`${node.id}=>${transition.targetNodeId as string}`] ?? 0;
          const color = traversalCount > 0 ? "#0f766e" : edgeColor(label);
          const edgeLabel = traversalCount > 0
            ? (label ? `${label} · x${traversalCount}` : `x${traversalCount}`)
            : label;
          return {
            id: `${node.id}-${transition.key}-${transition.targetNodeId}`,
            source: node.id,
            target: transition.targetNodeId as string,
            sourceHandle: transition.key,
            label: edgeLabel,
            type: "smoothstep",
            animated: traversalCount > 0,
            style: {
              stroke: color,
              strokeWidth: traversalCount > 0 ? Math.min(2.5 + traversalCount, 6) : 2.25,
              opacity: traversalCount > 0 ? 1 : 0.78,
            },
            markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
            labelStyle: { fill: color, fontSize: 10, fontWeight: 700 },
            labelBgStyle: { fill: traversalCount > 0 ? "#f0fdfa" : "#fff", fillOpacity: 0.96 },
            labelBgPadding: [5, 3] as [number, number],
            labelBgBorderRadius: 4,
          } satisfies Edge;
        }),
    )
  ), [draft.nodes, runOverlay?.edgeTraversals]);

  const selectedCanvasNode = useMemo(
    () => canvasNodes.find((node) => node.id === selectedNodeId) ?? null,
    [canvasNodes, selectedNodeId],
  );

  function handleNodesChange(changes: NodeChange<Node<CanvasNodeData>>[]) {
    if (!changes.some((change) => change.type === "position")) {
      return;
    }
    setCanvasNodes((current) => applyNodeChanges(changes, current));
  }

  const fitCanvasView = useCallback((duration = 280) => {
    if (!reactFlowInstance || canvasNodes.length === 0) {
      return;
    }

    reactFlowInstance.fitView({
      duration,
      padding: 0.12,
      minZoom: 0.28,
      maxZoom: 1.35,
    });
    setZoomPercent(Math.round((reactFlowInstance.getZoom?.() ?? 1) * 100));
  }, [canvasNodes.length, reactFlowInstance]);

  const adjustZoom = useCallback((direction: "in" | "out") => {
    if (!reactFlowInstance) {
      return;
    }

    if (direction === "in") {
      void reactFlowInstance.zoomIn({ duration: 180 });
    } else {
      void reactFlowInstance.zoomOut({ duration: 180 });
    }

    window.setTimeout(() => {
      setZoomPercent(Math.round((reactFlowInstance.getZoom?.() ?? 1) * 100));
    }, 190);
  }, [reactFlowInstance]);

  const setZoomLevel = useCallback((zoom: number) => {
    if (!reactFlowInstance) {
      return;
    }

    void reactFlowInstance.zoomTo(zoom, { duration: 180 });
    window.setTimeout(() => {
      setZoomPercent(Math.round((reactFlowInstance.getZoom?.() ?? zoom) * 100));
    }, 190);
  }, [reactFlowInstance]);

  const centerSelectedNode = useCallback(() => {
    if (!reactFlowInstance || !selectedCanvasNode) {
      return;
    }

    void reactFlowInstance.setCenter(
      selectedCanvasNode.position.x + CANVAS_NODE_WIDTH / 2,
      selectedCanvasNode.position.y + CANVAS_NODE_HEIGHT / 2,
      { zoom: Math.max(0.72, reactFlowInstance.getZoom?.() ?? 0.9), duration: 220 },
    );
    window.setTimeout(() => {
      setZoomPercent(Math.round((reactFlowInstance.getZoom?.() ?? 1) * 100));
    }, 230);
  }, [reactFlowInstance, selectedCanvasNode]);

  const jumpToNode = useCallback((nodeId: string) => {
    if (!reactFlowInstance) {
      return;
    }

    const targetNode = canvasNodes.find((node) => node.id === nodeId);
    if (!targetNode) {
      return;
    }

    onSelectNode(nodeId);
    void reactFlowInstance.setCenter(
      targetNode.position.x + CANVAS_NODE_WIDTH / 2,
      targetNode.position.y + CANVAS_NODE_HEIGHT / 2,
      { zoom: Math.max(0.78, reactFlowInstance.getZoom?.() ?? 0.9), duration: 220 },
    );
    window.setTimeout(() => {
      setZoomPercent(Math.round((reactFlowInstance.getZoom?.() ?? 1) * 100));
    }, 230);
  }, [canvasNodes, onSelectNode, reactFlowInstance]);

  useEffect(() => {
    if (!reactFlowInstance || canvasNodes.length === 0 || hasInitializedViewportRef.current) {
      return;
    }

    const animationFrame = window.requestAnimationFrame(() => {
      fitCanvasView(0);
      hasInitializedViewportRef.current = true;
    });

    return () => window.cancelAnimationFrame(animationFrame);
  }, [fitCanvasView, canvasNodes.length, reactFlowInstance]);

  useEffect(() => {
    if (!reactFlowInstance || canvasNodes.length === 0 || fitViewToken === 0) {
      return;
    }

    const animationFrame = window.requestAnimationFrame(() => {
      fitCanvasView();
    });

    return () => window.cancelAnimationFrame(animationFrame);
  }, [fitCanvasView, fitViewToken, canvasNodes.length, reactFlowInstance]);

  useEffect(() => {
    if (!containerRef.current || !reactFlowInstance) {
      return;
    }

    let previousWidth = containerRef.current.clientWidth;
    let previousHeight = containerRef.current.clientHeight;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }

      const nextWidth = entry.contentRect.width;
      const nextHeight = entry.contentRect.height;
      const widthDelta = Math.abs(nextWidth - previousWidth);
      const heightDelta = Math.abs(nextHeight - previousHeight);

      previousWidth = nextWidth;
      previousHeight = nextHeight;

      if (widthDelta < 24 && heightDelta < 24) {
        return;
      }

      fitCanvasView(180);
    });

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [fitCanvasView, reactFlowInstance]);

  useEffect(() => {
    if (!reactFlowInstance) {
      return;
    }

    setZoomPercent(Math.round((reactFlowInstance.getZoom?.() ?? 1) * 100));
  }, [reactFlowInstance]);

  // Delete key removes selected node; Escape deselects
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || ["input", "textarea", "select"].includes(target.tagName.toLowerCase()))
      ) {
        return;
      }
      if ((event.key === "Delete" || event.key === "Backspace") && selectedNodeId && onDeleteNode) {
        event.preventDefault();
        onDeleteNode(selectedNodeId);
      }
      if (event.key === "Escape") {
        setContextMenu(null);
        onSelectNode(null);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedNodeId, onDeleteNode, onSelectNode]);

  // Close context menu on outside click
  useEffect(() => {
    if (!contextMenu) return;
    function handleClick() { setContextMenu(null); }
    window.addEventListener("click", handleClick, { capture: true });
    return () => window.removeEventListener("click", handleClick, { capture: true });
  }, [contextMenu]);

  function handleConnectWithGuard(connection: Connection) {
    // Prevent self-loops
    if (connection.source === connection.target) return;
    // Prevent duplicate edges on the same handle
    const alreadyConnected = draft.nodes
      .find((n) => n.id === connection.source)
      ?.transitions.some((t) => t.key === (connection.sourceHandle ?? "next") && t.targetNodeId === connection.target);
    if (alreadyConnected) return;
    onConnectTransition(connection);
  }

  function handleNodeContextMenu(event: React.MouseEvent, node: Node<CanvasNodeData>) {
    event.preventDefault();
    setContextMenu({
      nodeId: node.id,
      x: event.clientX,
      y: event.clientY,
      isStart: draft.startNodeId === node.id,
    });
    onSelectNode(node.id);
  }

  function handleEdgeClick(_event: React.MouseEvent, edge: Edge) {
    if (!onDeleteEdge) return;
    // Edge id format: `${sourceId}-${transitionKey}-${targetId}`
    const parts = edge.id.split("-");
    if (parts.length < 2) return;
    const sourceId = edge.source;
    const transitionKey = edge.sourceHandle ?? "next";
    onDeleteEdge(sourceId, transitionKey);
  }

  function handleDragOver(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (!reactFlowInstance || !onDropNode) return;
    const kind = event.dataTransfer.getData("application/builder-node-kind") as BuilderNodeKind | "";
    if (!kind) return;
    const bounds = (event.currentTarget as HTMLDivElement).getBoundingClientRect();
    const position = reactFlowInstance.screenToFlowPosition({
      x: event.clientX - bounds.left,
      y: event.clientY - bounds.top,
    });
    onDropNode(kind, position);
  }

  return (
    <div ref={containerRef} className="relative h-full w-full">
      <div className="pointer-events-none absolute inset-x-3 top-3 z-10 flex items-start justify-between gap-2">
        <div className="pointer-events-auto rounded-2xl border border-neutral-200/80 bg-white/92 px-2 py-1.5 shadow-lg backdrop-blur">
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-neutral-400">Canvas</p>
          <p className="mt-0.5 text-[11px] text-neutral-500">Drag nodes freely, then fit or zoom when you need a tighter view.</p>
        </div>
        <div className="pointer-events-auto flex items-center gap-1 rounded-2xl border border-neutral-200/80 bg-white/92 p-1 shadow-lg backdrop-blur">
          <label className="sr-only" htmlFor="builder-v2-canvas-search">Search nodes</label>
          <input
            id="builder-v2-canvas-search"
            type="search"
            value={canvasSearchQuery}
            readOnly
            placeholder="Search…"
            className="w-[80px] rounded-xl border border-neutral-200 bg-white px-2 py-1.5 text-[11px] text-neutral-700 outline-none focus:border-yellow-400 focus:w-[120px] transition-all"
            onFocus={(e) => e.currentTarget.select()}
          />
          <label className="sr-only" htmlFor="builder-v2-canvas-jump">Jump to node</label>
          <select
            id="builder-v2-canvas-jump"
            value={selectedNodeId ?? ""}
            onChange={(event) => {
              if (!event.target.value) {
                return;
              }
              jumpToNode(event.target.value);
            }}
            className="max-w-[150px] rounded-xl border border-neutral-200 bg-white px-2 py-1.5 text-[11px] font-medium text-neutral-700 outline-none hover:border-neutral-300 focus:border-indigo-400"
          >
            <option value="">Jump to node</option>
            {draft.nodes.map((node) => (
              <option key={node.id} value={node.id}>{node.title} ({node.id})</option>
            ))}
          </select>
          <button
            type="button"
            onClick={centerSelectedNode}
            disabled={!selectedCanvasNode}
            className={`rounded-xl px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide ${selectedCanvasNode ? "text-neutral-700 hover:bg-neutral-100" : "cursor-not-allowed text-neutral-300"}`}
          >
            Center
          </button>
          <button
            type="button"
            onClick={() => adjustZoom("out")}
            className="rounded-xl px-2 py-1.5 text-sm font-semibold text-neutral-600 hover:bg-neutral-100"
          >
            -
          </button>
          <button
            type="button"
            onClick={() => fitCanvasView()}
            className="rounded-xl bg-neutral-900 px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-white hover:bg-neutral-800"
          >
            Fit
          </button>
          <button
            type="button"
            onClick={() => setZoomLevel(1)}
            className="rounded-xl px-2 py-1.5 text-[10px] font-semibold text-neutral-600 hover:bg-neutral-100"
          >
            {zoomPercent}%
          </button>
          <button
            type="button"
            onClick={() => setZoomLevel(0.75)}
            className="rounded-xl px-2 py-1.5 text-[10px] font-semibold text-neutral-600 hover:bg-neutral-100"
          >
            75%
          </button>
          <button
            type="button"
            onClick={() => adjustZoom("in")}
            className="rounded-xl px-2 py-1.5 text-sm font-semibold text-neutral-600 hover:bg-neutral-100"
          >
            +
          </button>
        </div>
      </div>
      <ReactFlow
        nodes={canvasNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.08, minZoom: 0.34, maxZoom: 1.35 }}
        onInit={setReactFlowInstance}
        onNodesChange={handleNodesChange}
        onNodeDragStop={(_, draggedNode, draggedNodes) => {
          const finalNodes = draggedNodes.length > 0 ? draggedNodes : [draggedNode];
          setCanvasNodes((current) => {
            const positionMap = new Map(finalNodes.map((node) => [node.id, node.position]));
            return current.map((node) => ({
              ...node,
              position: positionMap.get(node.id) ?? node.position,
            }));
          });
          onNodePositionCommit(mapNodePositions(finalNodes));
        }}
        onNodeClick={(_, node) => onSelectNode(node.id)}
        onPaneClick={() => { onSelectNode(null); setContextMenu(null); }}
        onMoveEnd={(_, viewport) => setZoomPercent(Math.round(viewport.zoom * 100))}
        onConnect={handleConnectWithGuard}
        defaultEdgeOptions={{ animated: false }}
        onlyRenderVisibleElements
        minZoom={0.34}
        maxZoom={1.8}
        className="bg-[radial-gradient(circle_at_top_left,_rgba(99,102,241,0.08),_transparent_35%),linear-gradient(180deg,#fcfcfd_0%,#f4f4f5_100%)]"
        onNodeContextMenu={handleNodeContextMenu}
        onEdgeClick={onDeleteEdge ? handleEdgeClick : undefined}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.1} color="#d4d4d8" />
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) => TYPE_BG[(node.data as CanvasNodeData).draftNode.kind] ?? "#9CA3AF"}
          className="!bottom-4 !bg-white/95 !border !border-neutral-200 !rounded-xl !shadow-lg"
        />
      </ReactFlow>

      {/* Right-click context menu — portal-style fixed overlay */}
      {contextMenu ? (
        <ContextMenuOverlay
          nodeId={contextMenu.nodeId}
          x={contextMenu.x}
          y={contextMenu.y}
          isStart={contextMenu.isStart}
          onSetStartNode={onSetStartNode}
          onDeleteNode={onDeleteNode}
          onDuplicateNode={onDuplicateNode}
          onClose={() => setContextMenu(null)}
        />
      ) : null}
    </div>
  );
}