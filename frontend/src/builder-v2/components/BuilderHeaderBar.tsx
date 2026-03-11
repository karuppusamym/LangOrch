"use client";

import type { BuilderDraftDocument } from "@/builder-v2/reference-contract";
import type { BuilderRunOverlay } from "@/builder-v2/execution/run-overlay";

export interface BuilderHeaderBarProps {
  shellTitle: string;
  shellSubtitle: string;
  isDirty: boolean;
  draftStatusText: string | null;
  draft: BuilderDraftDocument;
  validation: { errors: Array<{ nodeId?: string; message: string }>; warnings: Array<{ nodeId?: string; message: string }> };
  saving: boolean;
  savingDraft: boolean;
  configEditorError: string | null;
  guidedEditorErrors?: string[];
  canUndo: boolean;
  canRedo: boolean;
  compilePreviewLoading: boolean;
  runOverlay: BuilderRunOverlay | null;
  compileStatus: { label: string; className: string } | null;
  runSummary: { label: string; detail: string; className: string } | null;
  runStateTotals: { current: number; running: number; paused: number; failed: number } | null;
  traversedEdgeCount: number;
  onUndo: () => void;
  onRedo: () => void;
  onReset: () => void;
  onSaveDraft?: () => void | Promise<void>;
  onCompilePreview?: () => void | Promise<void>;
  onSaveWorkflow?: () => void | Promise<void>;
}

export function BuilderHeaderBar({
  shellTitle,
  shellSubtitle,
  isDirty,
  draftStatusText,
  draft,
  validation,
  saving,
  savingDraft,
  configEditorError,
  guidedEditorErrors = [],
  canUndo,
  canRedo,
  compilePreviewLoading,
  runOverlay,
  compileStatus,
  runSummary,
  runStateTotals,
  traversedEdgeCount,
  onUndo,
  onRedo,
  onReset,
  onSaveDraft,
  onCompilePreview,
  onSaveWorkflow,
}: BuilderHeaderBarProps) {
  const isDraftDirty = isDirty && !saving && !savingDraft;
  const isWorkflowDirty = isDirty && !saving && !savingDraft && validation.errors.length === 0;
  const hasEditorErrors = !!configEditorError || guidedEditorErrors.length > 0;
  const summaryBadges = [
    isDirty
      ? <span key="dirty" className="rounded-full bg-indigo-100 px-2.5 py-1 text-indigo-700">unsaved changes</span>
      : <span key="saved" className="rounded-full bg-neutral-100 px-2.5 py-1">saved state</span>,
    draftStatusText ? <span key="draft-status" className="rounded-full bg-sky-100 px-2.5 py-1 text-sky-700">{draftStatusText}</span> : null,
    compileStatus ? <span key="compile-status" className={`rounded-full px-2.5 py-1 ${compileStatus.className}`}>{compileStatus.label}</span> : null,
    runSummary ? <span key="run-summary" className={`rounded-full px-2.5 py-1 ${runSummary.className}`}>{runSummary.detail}</span> : null,
    runStateTotals && runStateTotals.current > 0 ? <span key="current" className="rounded-full bg-cyan-100 px-2.5 py-1 text-cyan-700">{runStateTotals.current} current</span> : null,
    runStateTotals && runStateTotals.running > 0 ? <span key="running" className="rounded-full bg-sky-100 px-2.5 py-1 text-sky-700">{runStateTotals.running} running</span> : null,
    runStateTotals && runStateTotals.paused > 0 ? <span key="paused" className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-700">{runStateTotals.paused} paused</span> : null,
    runStateTotals && runStateTotals.failed > 0 ? <span key="failed" className="rounded-full bg-rose-100 px-2.5 py-1 text-rose-700">{runStateTotals.failed} failed</span> : null,
    traversedEdgeCount > 0 ? <span key="traversed" className="rounded-full bg-teal-100 px-2.5 py-1 text-teal-700">{traversedEdgeCount} paths</span> : null,
    <span key="nodes" className="rounded-full bg-neutral-100 px-2.5 py-1">{draft.nodes.length} nodes</span>,
    <span key="start" className="rounded-full bg-neutral-100 px-2.5 py-1">start: {draft.startNodeId ?? "unset"}</span>,
    <span
      key="errors"
      className={`rounded-full px-2.5 py-1 ${validation.errors.length > 0 ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"}`}
    >
      {validation.errors.length} errors
    </span>,
    <span key="warnings" className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-700">{validation.warnings.length} warnings</span>,
    guidedEditorErrors.length > 0 ? <span key="editor-issues" className="rounded-full bg-rose-100 px-2.5 py-1 text-rose-700">{guidedEditorErrors.length} editor issues</span> : null,
  ].filter(Boolean);

  return (
    <div className="border-b border-neutral-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-semibold text-neutral-900">{shellTitle}</h1>
          <p className="text-xs text-neutral-500">{shellSubtitle}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-neutral-500">
            {summaryBadges}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5 text-xs text-neutral-500">
          {onSaveWorkflow ? (
            <>
              <button
                onClick={onUndo}
                disabled={!canUndo || saving || savingDraft}
                title="Undo (Ctrl+Z / Cmd+Z)"
                className="rounded-xl border border-neutral-200 px-2.5 py-1.5 text-[11px] font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
              >
                Undo
              </button>
              <button
                onClick={onRedo}
                disabled={!canRedo || saving || savingDraft}
                title="Redo (Ctrl+Y or Ctrl+Shift+Z / Cmd+Shift+Z)"
                className="rounded-xl border border-neutral-200 px-2.5 py-1.5 text-[11px] font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
              >
                Redo
              </button>
              <button
                onClick={onReset}
                disabled={!isDirty || saving || savingDraft}
                className="rounded-xl border border-neutral-200 px-2.5 py-1.5 text-[11px] font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
              >
                Reset
              </button>
              {onSaveDraft ? (
                <button
                  onClick={() => {
                    void onSaveDraft();
                  }}
                  disabled={!isDraftDirty || savingDraft || hasEditorErrors}
                  className="rounded-xl border border-sky-200 bg-sky-50 px-2.5 py-1.5 text-[11px] font-medium text-sky-700 hover:bg-sky-100 disabled:opacity-50"
                >
                  {savingDraft ? "Saving Draft..." : "Save Draft"}
                </button>
              ) : null}
              {onCompilePreview ? (
                <button
                  onClick={() => {
                    void onCompilePreview();
                  }}
                  disabled={compilePreviewLoading || saving || savingDraft || hasEditorErrors}
                  className="rounded-xl border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
                >
                  {compilePreviewLoading ? "Compiling..." : "Compile Preview"}
                </button>
              ) : null}
              <button
                onClick={() => {
                  void onSaveWorkflow();
                }}
                disabled={!isWorkflowDirty || saving || savingDraft || validation.errors.length > 0 || hasEditorErrors}
                className="rounded-xl bg-indigo-600 px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save Workflow"}
              </button>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
