"use client";

import { useCallback, useMemo, useState } from "react";

import type { BuilderDraftDocument } from "@/builder-v2/reference-contract";
import { loadDraftDocument } from "@/builder-v2/store/builder-store";

type DraftUpdater = BuilderDraftDocument | ((current: BuilderDraftDocument) => BuilderDraftDocument);

interface DraftHistoryState {
  past: BuilderDraftDocument[];
  present: BuilderDraftDocument;
  future: BuilderDraftDocument[];
  pendingHistoryBase: BuilderDraftDocument | null;
}

function cloneDraft(draft: BuilderDraftDocument): BuilderDraftDocument {
  return loadDraftDocument(draft);
}

/**
 * Structural fingerprint — much faster than JSON.stringify for large graphs.
 * Captures start node, node count, each node's id/kind/title/config-keys/transitions,
 * and skips position changes (those are recorded via recordHistory:false).
 */
function draftFingerprint(draft: BuilderDraftDocument): string {
  const parts: string[] = [draft.startNodeId ?? "", String(draft.nodes.length)];
  for (const node of draft.nodes) {
    const configKeys = Object.keys(node.config).sort().join(",");
    const configValues = Object.values(node.config)
      .map((v) => (v === null || v === undefined ? "" : String(v)))
      .join("|");
    const transitions = node.transitions
      .map((t) => `${t.key}:${t.targetNodeId ?? ""}`)
      .join(";");
    parts.push(`${node.id}|${node.kind}|${node.title}|${node.description ?? ""}|${node.agent ?? ""}|${configKeys}=${configValues}|${transitions}`);
  }
  return parts.join("\n");
}

function hasMeaningfulChange(currentDraft: BuilderDraftDocument, nextDraft: BuilderDraftDocument): boolean {
  return draftFingerprint(currentDraft) !== draftFingerprint(nextDraft);
}

export function useDraftHistory(initialDraft: BuilderDraftDocument) {
  const [history, setHistory] = useState<DraftHistoryState>(() => ({
    past: [],
    present: cloneDraft(initialDraft),
    future: [],
    pendingHistoryBase: null,
  }));

  const applyDraftChange = useCallback((updater: DraftUpdater, options?: { recordHistory?: boolean }) => {
    setHistory((currentHistory) => {
      const candidateDraft = typeof updater === "function"
        ? (updater as (current: BuilderDraftDocument) => BuilderDraftDocument)(currentHistory.present)
        : updater;
      const nextDraft = cloneDraft(candidateDraft);

      if (options?.recordHistory === false) {
        if (!hasMeaningfulChange(currentHistory.present, nextDraft)) {
          return currentHistory;
        }

        return {
          ...currentHistory,
          present: nextDraft,
          pendingHistoryBase: currentHistory.pendingHistoryBase ?? cloneDraft(currentHistory.present),
        };
      }

      if (!hasMeaningfulChange(currentHistory.present, nextDraft)) {
        if (currentHistory.pendingHistoryBase && hasMeaningfulChange(currentHistory.pendingHistoryBase, nextDraft)) {
          return {
            past: [...currentHistory.past, cloneDraft(currentHistory.pendingHistoryBase)],
            present: nextDraft,
            future: [],
            pendingHistoryBase: null,
          };
        }

        return currentHistory;
      }

      return {
        past: [
          ...currentHistory.past,
          cloneDraft(currentHistory.pendingHistoryBase ?? currentHistory.present),
        ],
        present: nextDraft,
        future: [],
        pendingHistoryBase: null,
      };
    });
  }, []);

  const resetDraftHistory = useCallback((nextDraft: BuilderDraftDocument) => {
    setHistory({
      past: [],
      present: cloneDraft(nextDraft),
      future: [],
      pendingHistoryBase: null,
    });
  }, []);

  const undoDraftChange = useCallback(() => {
    setHistory((currentHistory) => {
      if (currentHistory.past.length === 0) {
        return currentHistory;
      }

      const previousDraft = currentHistory.past[currentHistory.past.length - 1];
      return {
        past: currentHistory.past.slice(0, -1),
        present: cloneDraft(previousDraft),
        future: [cloneDraft(currentHistory.present), ...currentHistory.future],
        pendingHistoryBase: null,
      };
    });
  }, []);

  const redoDraftChange = useCallback(() => {
    setHistory((currentHistory) => {
      if (currentHistory.future.length === 0) {
        return currentHistory;
      }

      const [nextDraft, ...remainingFuture] = currentHistory.future;
      return {
        past: [...currentHistory.past, cloneDraft(currentHistory.present)],
        present: cloneDraft(nextDraft),
        future: remainingFuture,
        pendingHistoryBase: null,
      };
    });
  }, []);

  return useMemo(() => ({
    draft: history.present,
    applyDraftChange,
    resetDraftHistory,
    undoDraftChange,
    redoDraftChange,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
    historyDepth: history.past.length,
  }), [applyDraftChange, history.future.length, history.past.length, history.present, redoDraftChange, resetDraftHistory, undoDraftChange]);
}