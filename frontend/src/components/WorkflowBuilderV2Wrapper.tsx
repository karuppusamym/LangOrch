"use client";

import { useEffect, useMemo, useState } from "react";

import { BuilderShell } from "@/builder-v2/components/BuilderShell";
import type { BuilderDraftDocument, CkpWorkflowGraph } from "@/builder-v2/reference-contract";
import { explainProcedure, listRunEvents, listRuns, saveProcedureBuilderDraft } from "@/lib/api";
import type { ExplainReport, Run, RunEvent } from "@/lib/types";
import { createEmptyDraftDocument, loadDraftDocument } from "@/builder-v2/store/builder-store";
import { ckpWorkflowToDraftDocument } from "@/builder-v2/transforms/ckp-to-draft";
import { buildBuilderRunOverlay } from "@/builder-v2/execution/run-overlay";

export default function WorkflowBuilderV2Wrapper({
  procedureId,
  procedureVersion,
  baseCkpJson,
  initialWorkflowGraph,
  initialBuilderDraft,
  initialBuilderDraftUpdatedAt,
  onSaveWorkflow,
  savingWorkflow,
}: {
  procedureId: string;
  procedureVersion: string;
  baseCkpJson: Record<string, unknown>;
  initialWorkflowGraph: Record<string, unknown> | null;
  initialBuilderDraft?: Record<string, unknown> | null;
  initialBuilderDraftUpdatedAt?: string | null;
  onSaveWorkflow: (workflowGraph: CkpWorkflowGraph) => void | Promise<void>;
  savingWorkflow?: boolean;
}) {
  const [mounted, setMounted] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(initialBuilderDraftUpdatedAt ?? null);
  const [latestRun, setLatestRun] = useState<Run | null>(null);
  const [latestRunEvents, setLatestRunEvents] = useState<RunEvent[]>([]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    setDraftSavedAt(initialBuilderDraftUpdatedAt ?? null);
  }, [initialBuilderDraftUpdatedAt]);

  useEffect(() => {
    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    async function loadLatestRun() {
      try {
        const runs = await listRuns({ procedure_id: procedureId, limit: 1, order: "desc" });
        const nextRun = runs[0] ?? null;

        if (!nextRun) {
          if (!cancelled) {
            setLatestRun(null);
            setLatestRunEvents([]);
          }
          return;
        }

        const events = await listRunEvents(nextRun.run_id);
        if (!cancelled) {
          setLatestRun(nextRun);
          setLatestRunEvents(events);
        }
      } catch {
        if (!cancelled) {
          setLatestRun(null);
          setLatestRunEvents([]);
        }
      }
    }

    void loadLatestRun();
    intervalId = setInterval(() => {
      if (["created", "pending", "running", "waiting_approval"].includes(latestRun?.status ?? "")) {
        void loadLatestRun();
      }
    }, 5000);

    return () => {
      cancelled = true;
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [latestRun?.status, procedureId]);

  const initialDraft = useMemo<BuilderDraftDocument>(() => {
    if (initialBuilderDraft) {
      return loadDraftDocument(initialBuilderDraft as unknown as BuilderDraftDocument);
    }

    if (initialWorkflowGraph) {
      return ckpWorkflowToDraftDocument(initialWorkflowGraph, {
        procedureId,
        procedureVersion,
      });
    }

    return createEmptyDraftDocument({
      procedureId,
      procedureVersion,
    });
  }, [initialBuilderDraft, initialWorkflowGraph, procedureId, procedureVersion]);

  async function handleSaveDraft(draft: BuilderDraftDocument) {
    setSavingDraft(true);
    try {
      const result = await saveProcedureBuilderDraft(procedureId, procedureVersion, draft as unknown as Record<string, unknown>);
      setDraftSavedAt(result.updated_at);
    } finally {
      setSavingDraft(false);
    }
  }

  async function handleSaveWorkflow(workflowGraph: CkpWorkflowGraph, draft: BuilderDraftDocument) {
    await handleSaveDraft(draft);
    await onSaveWorkflow(workflowGraph);
  }

  async function handleCompilePreview(workflowGraph: CkpWorkflowGraph): Promise<ExplainReport> {
    const candidateCkp = {
      ...baseCkpJson,
      procedure_id: procedureId,
      version: procedureVersion,
      workflow_graph: workflowGraph,
    };
    return explainProcedure(procedureId, procedureVersion, { ckpJson: candidateCkp });
  }

  const draftStatusText = draftSavedAt
    ? `draft saved ${new Date(draftSavedAt).toLocaleString()}`
    : null;

  const runOverlay = useMemo(
    () => buildBuilderRunOverlay(latestRun, latestRunEvents),
    [latestRun, latestRunEvents],
  );

  if (!mounted) {
    return (
      <div className="flex h-[740px] w-full items-center justify-center rounded-xl border border-gray-200 bg-gray-50">
        <p className="text-sm text-gray-400">Loading workflow builder…</p>
      </div>
    );
  }

  return (
    <BuilderShell
      initialDraft={initialDraft}
      onSave={handleSaveWorkflow}
      onSaveDraft={handleSaveDraft}
      onCompilePreview={handleCompilePreview}
      saving={savingWorkflow}
      savingDraft={savingDraft}
      draftStatusText={draftStatusText}
      runOverlay={runOverlay}
      shellTitle="Workflow Builder V2"
      shellSubtitle="Draft-first workflow authoring with persisted Builder V2 drafts and canonical CKP workflow saves."
    />
  );
}