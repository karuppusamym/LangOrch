"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Connection } from "@xyflow/react";

import type { BuilderDraftDocument, CkpWorkflowGraph } from "@/builder-v2/reference-contract";
import type { ExplainReport } from "@/lib/types";
import { BuilderCanvas } from "@/builder-v2/canvas/BuilderCanvas";
import { BuilderHeaderBar } from "@/builder-v2/components/BuilderHeaderBar";
import { BuilderLeftRail } from "@/builder-v2/components/BuilderLeftRail";
import { BuilderWorkspacePanels } from "@/builder-v2/components/BuilderWorkspacePanels";
import type { BuilderRunOverlay } from "@/builder-v2/execution/run-overlay";
import { InspectorPanel } from "@/builder-v2/inspector/InspectorPanel";
import { builderNodeDefinitions, getBuilderNodeDefinition } from "@/builder-v2/registry/node-definitions";
import { useBuilderKeyboardShortcuts } from "@/builder-v2/state/use-builder-keyboard-shortcuts";
import { useDraftHistory } from "@/builder-v2/state/use-draft-history";
import {
  addDraftNode,
  addDraftTransition,
  autoLayoutDraft,
  loadDraftDocument,
  removeDraftNode,
  removeDraftTransition,
  setDraftStartNode,
  updateDraftNodeConfig,
  updateDraftNodePositions,
  updateDraftTransition,
  updateDraftNode,
} from "@/builder-v2/store/builder-store";
import { WORKFLOW_TEMPLATES } from "@/builder-v2/legacy/catalog";
import { draftDocumentToCkpWorkflow } from "@/builder-v2/transforms/draft-to-ckp";
import { ckpWorkflowToDraftDocument } from "@/builder-v2/transforms/ckp-to-draft";
import { validateDraftDocument } from "@/builder-v2/validation/validate-draft";

interface BuilderShellProps {
  initialDraft: BuilderDraftDocument;
  onSave?: (workflowGraph: CkpWorkflowGraph, draft: BuilderDraftDocument) => void | Promise<void>;
  onSaveDraft?: (draft: BuilderDraftDocument) => void | Promise<void>;
  onCompilePreview?: (workflowGraph: CkpWorkflowGraph, draft: BuilderDraftDocument) => Promise<ExplainReport>;
  saving?: boolean;
  savingDraft?: boolean;
  draftStatusText?: string | null;
  shellTitle?: string;
  shellSubtitle?: string;
  runOverlay?: BuilderRunOverlay | null;
}

const WORKSPACE_DOCK_HEIGHT_STEPS = [168, 192, 216, 240, 264, 288, 312, 336, 360] as const;

function getWorkspaceDockHeightClass(height: number) {
  const closestHeight = WORKSPACE_DOCK_HEIGHT_STEPS.reduce((closest, candidate) => (
    Math.abs(candidate - height) < Math.abs(closest - height) ? candidate : closest
  ));

  switch (closestHeight) {
    case 168:
      return "h-[168px]";
    case 192:
      return "h-[192px]";
    case 216:
      return "h-[216px]";
    case 240:
      return "h-[240px]";
    case 264:
      return "h-[264px]";
    case 288:
      return "h-[288px]";
    case 312:
      return "h-[312px]";
    case 336:
      return "h-[336px]";
    default:
      return "h-[360px]";
  }
}

export function BuilderShell({
  initialDraft,
  onSave,
  onSaveDraft,
  onCompilePreview,
  saving = false,
  savingDraft = false,
  draftStatusText = null,
  shellTitle = "Builder V2 Reference Shell",
  shellSubtitle = "Draft-first authoring, separated from CKP export and ready for validation and publish flow.",
  runOverlay = null,
}: BuilderShellProps) {
  const {
    draft,
    applyDraftChange,
    resetDraftHistory,
    undoDraftChange,
    redoDraftChange,
    canUndo,
    canRedo,
  } = useDraftHistory(initialDraft);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(draft.nodes[0]?.id ?? null);
  const [configEditorValue, setConfigEditorValue] = useState("{}");
  const [configEditorError, setConfigEditorError] = useState<string | null>(null);
  const [compilePreview, setCompilePreview] = useState<ExplainReport | null>(null);
  const [compilePreviewLoading, setCompilePreviewLoading] = useState(false);
  const [compilePreviewError, setCompilePreviewError] = useState<string | null>(null);
  const [guidedEditorErrors, setGuidedEditorErrors] = useState<string[]>([]);
  const [fitViewToken, setFitViewToken] = useState(0);
  const [workspacePanelsOpen, setWorkspacePanelsOpen] = useState(false);
  const [workspacePanelsHeight, setWorkspacePanelsHeight] = useState(168);
  const [leftRailOpen, setLeftRailOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [maximizeCanvas, setMaximizeCanvas] = useState(false);
  const [isWideWorkspace, setIsWideWorkspace] = useState(false);
  const [paletteFilter, setPaletteFilter] = useState("");
  const [outlineFilter, setOutlineFilter] = useState("");
  const [savedDraftSnapshot, setSavedDraftSnapshot] = useState(() => JSON.stringify(loadDraftDocument(initialDraft)));
  const [savedWorkflowSnapshot, setSavedWorkflowSnapshot] = useState(() => JSON.stringify(draftDocumentToCkpWorkflow(loadDraftDocument(initialDraft))));
  const dockResizeStateRef = useRef<{ startY: number; startHeight: number } | null>(null);

  const initialWorkflowGraphString = useMemo(
    () => JSON.stringify(draftDocumentToCkpWorkflow(loadDraftDocument(initialDraft))),
    [initialDraft],
  );

  const selectedNode = useMemo(
    () => draft.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [draft.nodes, selectedNodeId],
  );

  const selectedNodeDefinition = useMemo(
    () => selectedNode ? getBuilderNodeDefinition(selectedNode.kind) : null,
    [selectedNode],
  );

  const validation = useMemo(() => validateDraftDocument(draft), [draft]);

  const issuesByNodeId = useMemo(() => {
    const counts = new Map<string, { errors: number; warnings: number }>();
    for (const issue of validation.errors) {
      if (!issue.nodeId) continue;
      const current = counts.get(issue.nodeId) ?? { errors: 0, warnings: 0 };
      counts.set(issue.nodeId, { ...current, errors: current.errors + 1 });
    }
    for (const issue of validation.warnings) {
      if (!issue.nodeId) continue;
      const current = counts.get(issue.nodeId) ?? { errors: 0, warnings: 0 };
      counts.set(issue.nodeId, { ...current, warnings: current.warnings + 1 });
    }
    return counts;
  }, [validation.errors, validation.warnings]);

  const filteredNodeDefinitions = useMemo(() => {
    const query = paletteFilter.trim().toLowerCase();
    if (!query) return builderNodeDefinitions;
    return builderNodeDefinitions.filter((definition) =>
      [definition.title, definition.kind, definition.category].some((value) => value.toLowerCase().includes(query)),
    );
  }, [paletteFilter]);

  const filteredDraftNodes = useMemo(() => {
    const query = outlineFilter.trim().toLowerCase();
    const sortedNodes = [...draft.nodes].sort((left, right) => {
      if (left.id === draft.startNodeId) return -1;
      if (right.id === draft.startNodeId) return 1;
      return left.title.localeCompare(right.title);
    });
    if (!query) return sortedNodes;
    return sortedNodes.filter((node) =>
      [node.id, node.title, node.kind, node.description ?? ""].some((value) => value.toLowerCase().includes(query)),
    );
  }, [draft.nodes, draft.startNodeId, outlineFilter]);

  const compileStatus = useMemo(() => {
    if (compilePreviewLoading) {
      return { label: "compile checking", className: "bg-sky-100 text-sky-700" };
    }
    if (compilePreviewError) {
      return { label: "compile blocked", className: "bg-red-100 text-red-700" };
    }
    if (!compilePreview) {
      return null;
    }
    if (compilePreview.variables.missing_inputs.length > 0) {
      return { label: "compile has blockers", className: "bg-amber-100 text-amber-700" };
    }
    return { label: "compile ready", className: "bg-emerald-100 text-emerald-700" };
  }, [compilePreview, compilePreviewError, compilePreviewLoading]);

  const runSummary = useMemo(() => {
    if (!runOverlay) {
      return null;
    }
    const isActive = ["created", "pending", "running", "waiting_approval"].includes(runOverlay.status);
    return {
      label: isActive ? "recent run active" : "recent run",
      className: isActive ? "bg-sky-100 text-sky-700" : runOverlay.status === "failed" ? "bg-red-100 text-red-700" : "bg-neutral-100 text-neutral-700",
      detail: `${runOverlay.status.replace(/_/g, " ")} · ${runOverlay.runId.slice(0, 8)}${runOverlay.lastNodeId ? ` · ${runOverlay.lastNodeId}` : ""}`,
      isActive,
    };
  }, [runOverlay]);

  const runStateTotals = useMemo(() => {
    if (!runOverlay) {
      return null;
    }
    return Object.values(runOverlay.nodeStates).reduce(
      (totals, summary) => {
        totals[summary.state] += 1;
        return totals;
      },
      {
        idle: 0,
        current: 0,
        running: 0,
        completed: 0,
        failed: 0,
        paused: 0,
        sla_breached: 0,
      },
    );
  }, [runOverlay]);

  const traversedEdgeCount = useMemo(() => {
    if (!runOverlay) {
      return 0;
    }
    return Object.keys(runOverlay.edgeTraversals).length;
  }, [runOverlay]);

  const previewJson = useMemo(
    () => JSON.stringify(draftDocumentToCkpWorkflow(draft), null, 2),
    [draft],
  );

  const currentWorkflowGraphString = useMemo(
    () => JSON.stringify(draftDocumentToCkpWorkflow(draft)),
    [draft],
  );

  const currentDraftString = useMemo(() => JSON.stringify(draft), [draft]);

  const isDraftDirty = currentDraftString !== savedDraftSnapshot;
  const isWorkflowDirty = currentWorkflowGraphString !== savedWorkflowSnapshot;
  const isDirty = isDraftDirty || isWorkflowDirty;
  const workspaceDockHeightClass = useMemo(() => getWorkspaceDockHeightClass(workspacePanelsHeight), [workspacePanelsHeight]);

  useBuilderKeyboardShortcuts({
    canUndo: canUndo && !saving && !savingDraft,
    canRedo: canRedo && !saving && !savingDraft,
    onUndo: undoDraftChange,
    onRedo: redoDraftChange,
  });

  useEffect(() => {
    const nextDraft = loadDraftDocument(initialDraft);
    resetDraftHistory(nextDraft);
    setSelectedNodeId(nextDraft.nodes[0]?.id ?? null);
    setSavedDraftSnapshot(JSON.stringify(nextDraft));
    setSavedWorkflowSnapshot(JSON.stringify(draftDocumentToCkpWorkflow(nextDraft)));
    setCompilePreview(null);
    setCompilePreviewError(null);
    setGuidedEditorErrors([]);
    setFitViewToken((current) => current + 1);
  }, [initialDraft, resetDraftHistory]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const mediaQuery = window.matchMedia("(min-width: 1536px)");
    const applyLayoutMode = (matches: boolean) => {
      setIsWideWorkspace(matches);
      setLeftRailOpen(matches);
      setInspectorOpen(matches);
    };

    applyLayoutMode(mediaQuery.matches);

    const handleChange = (event: MediaQueryListEvent) => applyLayoutMode(event.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (!selectedNode && draft.nodes.length > 0) {
      setSelectedNodeId(draft.nodes[0]?.id ?? null);
    }
    if (selectedNodeId && !draft.nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(draft.nodes[0]?.id ?? null);
    }
  }, [draft.nodes, selectedNode, selectedNodeId]);

  useEffect(() => {
    if (!selectedNode) {
      setConfigEditorValue("{}");
      setConfigEditorError(null);
      setGuidedEditorErrors([]);
      if (!isWideWorkspace) {
        setInspectorOpen(false);
      }
      return;
    }
    setConfigEditorValue(JSON.stringify(selectedNode.config, null, 2));
    setConfigEditorError(null);
    setInspectorOpen(true);
  }, [isWideWorkspace, selectedNode]);

  function commitConfigEditor(value: string) {
    if (!selectedNode) return;
    setConfigEditorValue(value);
    try {
      const parsed = JSON.parse(value) as Record<string, unknown>;
      applyDraftChange((current) => updateDraftNode(current, selectedNode.id, { config: parsed }));
      setConfigEditorError(null);
    } catch {
      setConfigEditorError("Advanced config must be valid JSON.");
    }
  }

  function updateSelectedNodeConfig(patch: Record<string, unknown>) {
    if (!selectedNode) return;
    applyDraftChange((current) => updateDraftNodeConfig(current, selectedNode.id, patch));
  }

  function handleConnectTransition(connection: Connection) {
    if (!connection.source || !connection.target) return;
    const transitionKey = connection.sourceHandle ?? "next";
    applyDraftChange((current) => {
      const sourceNode = current.nodes.find((node) => node.id === connection.source);
      const existing = sourceNode?.transitions.find((transition) => transition.key === transitionKey);
      if (existing) {
        return updateDraftTransition(current, connection.source as string, transitionKey, { targetNodeId: connection.target });
      }
      return updateDraftTransition(
        addDraftTransition(current, connection.source as string, transitionKey),
        connection.source as string,
        transitionKey,
        { targetNodeId: connection.target },
      );
    });
    setSelectedNodeId(connection.source);
  }

  async function handleSave() {
    if (!onSave || validation.errors.length > 0 || configEditorError) return;
    await onSave(draftDocumentToCkpWorkflow(draft), draft);
    setSavedDraftSnapshot(currentDraftString);
    setSavedWorkflowSnapshot(currentWorkflowGraphString);
  }

  async function handleSaveDraft() {
    if (!onSaveDraft || configEditorError) return;
    await onSaveDraft(draft);
    setSavedDraftSnapshot(currentDraftString);
  }

  async function handleCompilePreview() {
    if (!onCompilePreview || configEditorError) return;
    setCompilePreviewLoading(true);
    setCompilePreviewError(null);
    try {
      const result = await onCompilePreview(draftDocumentToCkpWorkflow(draft), draft);
      setCompilePreview(result);
    } catch (error) {
      setCompilePreviewError(error instanceof Error ? error.message : "Compile preview failed");
      setCompilePreview(null);
    } finally {
      setCompilePreviewLoading(false);
    }
  }

  function handleDockResizeStart(event: React.PointerEvent<HTMLDivElement>) {
    dockResizeStateRef.current = {
      startY: event.clientY,
      startHeight: workspacePanelsHeight,
    };

    const handlePointerMove = (moveEvent: PointerEvent) => {
      if (!dockResizeStateRef.current || typeof window === "undefined") {
        return;
      }

      const nextHeight = dockResizeStateRef.current.startHeight + (dockResizeStateRef.current.startY - moveEvent.clientY);
      const maxHeight = Math.max(220, Math.round(window.innerHeight * 0.42));
      const boundedHeight = Math.min(maxHeight, Math.max(168, nextHeight));
      const snappedHeight = WORKSPACE_DOCK_HEIGHT_STEPS.reduce((closest, candidate) => (
        Math.abs(candidate - boundedHeight) < Math.abs(closest - boundedHeight) ? candidate : closest
      ));
      setWorkspacePanelsHeight(snappedHeight);
    };

    const handlePointerUp = () => {
      dockResizeStateRef.current = null;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
  }

  return (
    <div className="flex min-h-[calc(100vh-4rem)] flex-col bg-neutral-50">
      <BuilderHeaderBar
        shellTitle={shellTitle}
        shellSubtitle={shellSubtitle}
        isDirty={isDirty}
        draftStatusText={draftStatusText}
        draft={draft}
        validation={validation}
        saving={saving}
        savingDraft={savingDraft}
        configEditorError={configEditorError}
        guidedEditorErrors={guidedEditorErrors}
        canUndo={canUndo}
        canRedo={canRedo}
        compilePreviewLoading={compilePreviewLoading}
        runOverlay={runOverlay}
        compileStatus={compileStatus}
        runSummary={runSummary}
        runStateTotals={runStateTotals}
        traversedEdgeCount={traversedEdgeCount}
        onUndo={undoDraftChange}
        onRedo={redoDraftChange}
        onReset={() => {
          const nextDraft = loadDraftDocument(initialDraft);
          resetDraftHistory(nextDraft);
          setSelectedNodeId(nextDraft.nodes[0]?.id ?? null);
        }}
        onSaveDraft={onSaveDraft ? handleSaveDraft : undefined}
        onCompilePreview={onCompilePreview ? handleCompilePreview : undefined}
        onSaveWorkflow={onSave ? handleSave : undefined}
      />

      <div className="relative flex flex-1 overflow-hidden bg-neutral-200">
        {!maximizeCanvas && !isWideWorkspace && (leftRailOpen || inspectorOpen) ? (
          <button
            type="button"
            aria-label="Close builder overlays"
            onClick={() => {
              setLeftRailOpen(false);
              setInspectorOpen(false);
            }}
            className="absolute inset-0 z-10 bg-neutral-950/10"
          />
        ) : null}

        <aside
          className={maximizeCanvas
            ? "hidden"
            : isWideWorkspace
            ? "z-20 w-[248px] overflow-auto border-r border-neutral-200 bg-white"
            : leftRailOpen
              ? "absolute inset-y-0 left-0 z-20 w-[min(248px,calc(100vw-3rem))] overflow-auto border-r border-neutral-200 bg-white shadow-2xl"
              : "hidden"}
        >
          <BuilderLeftRail
            draft={draft}
            selectedNodeId={selectedNodeId}
            paletteFilter={paletteFilter}
            outlineFilter={outlineFilter}
            filteredNodeDefinitions={filteredNodeDefinitions}
            filteredDraftNodes={filteredDraftNodes}
            issuesByNodeId={issuesByNodeId}
            validation={validation}
            runOverlay={runOverlay}
            runSummary={runSummary}
            runStateTotals={runStateTotals}
            traversedEdgeCount={traversedEdgeCount}
            onPaletteFilterChange={setPaletteFilter}
            onOutlineFilterChange={setOutlineFilter}
            onAddNode={(kind) => applyDraftChange((current) => {
              const nextDraft = addDraftNode(current, kind);
              setSelectedNodeId(nextDraft.nodes.at(-1)?.id ?? null);
              setFitViewToken((token) => token + 1);
              if (!isWideWorkspace) {
                setLeftRailOpen(false);
                setInspectorOpen(true);
              }
              return nextDraft;
            })}
            onSelectNode={(nodeId) => {
              setSelectedNodeId(nodeId);
              if (!isWideWorkspace && nodeId) {
                setLeftRailOpen(false);
                setInspectorOpen(true);
              }
            }}
            onApplyTemplate={(templateName) => {
              const template = WORKFLOW_TEMPLATES.find((candidate) => candidate.name === templateName);
              if (!template) return;
              const nextDraft = ckpWorkflowToDraftDocument(
                template.workflowGraph,
                { procedureId: template.name.toLowerCase().replace(/\s+/g, "-"), procedureVersion: "template" },
              );
              resetDraftHistory(nextDraft);
              setSelectedNodeId(nextDraft.nodes[0]?.id ?? null);
              setFitViewToken((token) => token + 1);
              if (!isWideWorkspace) {
                setLeftRailOpen(false);
                setInspectorOpen(true);
              }
            }}
          />
        </aside>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-neutral-50">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-neutral-200 bg-white px-3 py-2">
            <div>
              <p className="text-xs font-bold uppercase tracking-widest text-neutral-400">Draft Graph</p>
              <p className="text-xs text-neutral-500">Connect nodes on the canvas and edit behavior in the inspector.</p>
              {selectedNode ? (
                <p className="mt-1 text-xs text-neutral-500">Selected: <span className="font-semibold text-neutral-700">{selectedNode.title}</span> <span className="text-neutral-400">({selectedNode.id})</span></p>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  setMaximizeCanvas((current) => !current);
                  setFitViewToken((token) => token + 1);
                }}
                className={`rounded-xl border px-3 py-2 text-sm font-medium ${maximizeCanvas ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-50"}`}
              >
                {maximizeCanvas ? "Restore Shell" : "Maximize Canvas"}
              </button>
              <button
                type="button"
                onClick={() => setLeftRailOpen((current) => !current)}
                disabled={maximizeCanvas}
                className={`rounded-xl border px-3 py-1.5 text-sm font-medium ${maximizeCanvas ? "cursor-not-allowed border-neutral-200 bg-neutral-100 text-neutral-400" : leftRailOpen ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-50"}`}
              >
                {leftRailOpen ? "Hide Library" : "Show Library"}
              </button>
              <button
                type="button"
                onClick={() => setInspectorOpen((current) => !current)}
                disabled={maximizeCanvas}
                className={`rounded-xl border px-3 py-1.5 text-sm font-medium ${maximizeCanvas ? "cursor-not-allowed border-neutral-200 bg-neutral-100 text-neutral-400" : inspectorOpen ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-50"}`}
              >
                {inspectorOpen ? "Hide Inspector" : selectedNode ? "Open Inspector" : "Inspector"}
              </button>
              <button
                onClick={() => {
                  applyDraftChange((current) => autoLayoutDraft(current));
                  setFitViewToken((token) => token + 1);
                }}
                className="rounded-xl border border-neutral-200 bg-white px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
              >
                Auto Layout
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1">
            <BuilderCanvas
              draft={draft}
              selectedNodeId={selectedNodeId}
              runOverlay={runOverlay}
              fitViewToken={fitViewToken}
              onSelectNode={(nodeId) => {
                setSelectedNodeId(nodeId);
                if (!isWideWorkspace) {
                  setInspectorOpen(Boolean(nodeId));
                }
              }}
              onNodePositionPreview={(positions) => applyDraftChange(
                (current) => updateDraftNodePositions(current, positions),
                { recordHistory: false },
              )}
              onNodePositionCommit={(positions) => applyDraftChange((current) => updateDraftNodePositions(current, positions))}
              onConnectTransition={handleConnectTransition}
            />
          </div>

          {!maximizeCanvas ? (
            <div className={`${workspacePanelsOpen ? workspaceDockHeightClass : "h-auto"} shrink-0 border-t border-neutral-200 bg-white`}>
              {workspacePanelsOpen ? (
                <div
                  role="separator"
                  aria-orientation="horizontal"
                  onPointerDown={handleDockResizeStart}
                  className="flex h-3 cursor-row-resize items-center justify-center border-b border-neutral-200 bg-neutral-50 text-[10px] font-medium uppercase tracking-widest text-neutral-400"
                >
                  Resize Panels
                </div>
              ) : null}
              <BuilderWorkspacePanels
                validation={validation}
                compilePreviewLoading={compilePreviewLoading}
                compilePreviewError={compilePreviewError}
                compilePreview={compilePreview}
                previewJson={previewJson}
                isOpen={workspacePanelsOpen}
                onToggleOpen={() => setWorkspacePanelsOpen((current) => !current)}
                onSelectNode={setSelectedNodeId}
              />
            </div>
          ) : null}
        </main>

        <aside
          className={maximizeCanvas
            ? "hidden"
            : isWideWorkspace
            ? "z-20 w-[288px] overflow-auto border-l border-neutral-200 bg-white p-2.5"
            : inspectorOpen
              ? "absolute inset-y-0 right-0 z-20 w-[min(288px,calc(100vw-3rem))] overflow-auto border-l border-neutral-200 bg-white p-2.5 shadow-2xl"
              : "hidden"}
        >
          <div className="mb-3 flex items-center justify-between gap-3">
            <p className="text-xs font-bold uppercase tracking-widest text-neutral-400">Inspector</p>
            {!isWideWorkspace ? (
              <button
                type="button"
                onClick={() => setInspectorOpen(false)}
                className="rounded-lg border border-neutral-200 px-2.5 py-1 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
              >
                Close
              </button>
            ) : null}
          </div>
          <InspectorPanel
            draft={draft}
            selectedNode={selectedNode}
            selectedNodeDefinition={selectedNodeDefinition}
            configEditorValue={configEditorValue}
            configEditorError={configEditorError}
            onEditorValidationChange={setGuidedEditorErrors}
            onUpdateNode={(patch) => {
              if (!selectedNode) return;
              applyDraftChange((current) => updateDraftNode(current, selectedNode.id, patch));
            }}
            onUpdateConfig={updateSelectedNodeConfig}
            onSetStartNode={() => {
              if (!selectedNode) return;
              applyDraftChange((current) => setDraftStartNode(current, selectedNode.id));
            }}
            onDeleteNode={() => {
              if (!selectedNode) return;
              applyDraftChange((current) => removeDraftNode(current, selectedNode.id));
            }}
            onAddTransition={(key) => {
              if (!selectedNode) return;
              applyDraftChange((current) => addDraftTransition(current, selectedNode.id, key ?? `path_${selectedNode.transitions.length + 1}`));
            }}
            onUpdateTransition={(transitionKey, patch) => {
              if (!selectedNode) return;
              applyDraftChange((current) => updateDraftTransition(current, selectedNode.id, transitionKey, patch));
            }}
            onRemoveTransition={(transitionKey) => {
              if (!selectedNode) return;
              applyDraftChange((current) => removeDraftTransition(current, selectedNode.id, transitionKey));
            }}
            onConfigEditorChange={setConfigEditorValue}
            onCommitConfigEditor={commitConfigEditor}
          />
        </aside>
      </div>
    </div>
  );
}