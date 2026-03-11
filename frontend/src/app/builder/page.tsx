"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import type { CkpWorkflowGraph } from "@/builder-v2/reference-contract";
import WorkflowBuilderV2Wrapper from "@/components/WorkflowBuilderV2Wrapper";
import { useToast } from "@/components/Toast";
import { getProcedure, listProcedures, listVersions, updateProcedure } from "@/lib/api";
import type { Procedure, ProcedureDetail } from "@/lib/types";

const PROCEDURE_PAGE_SIZE = 9;
const RECENT_PROCEDURES_STORAGE_KEY = "langorch.builder.recent-procedures";
const LAST_BUILDER_SESSION_STORAGE_KEY = "langorch.builder.last-session";
const MAX_RECENT_PROCEDURES = 6;

type RecentProcedureEntry = {
  procedureId: string;
  version: string;
  name: string;
  description: string;
  status: string;
  openedAt: string;
};

function statusClass(status: string | null | undefined): string {
  if (status === "active") return "bg-emerald-100 text-emerald-700";
  if (status === "draft") return "bg-amber-100 text-amber-700";
  return "bg-neutral-100 text-neutral-600";
}

function readRecentProcedures(): RecentProcedureEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RECENT_PROCEDURES_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as RecentProcedureEntry[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeRecentProcedures(entries: RecentProcedureEntry[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(RECENT_PROCEDURES_STORAGE_KEY, JSON.stringify(entries));
}

function writeLastBuilderSession(entry: RecentProcedureEntry) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(LAST_BUILDER_SESSION_STORAGE_KEY, JSON.stringify(entry));
}

function readLastBuilderSession(): RecentProcedureEntry | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LAST_BUILDER_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as RecentProcedureEntry;
    return parsed?.procedureId ? parsed : null;
  } catch {
    return null;
  }
}

function BuilderPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();

  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [versions, setVersions] = useState<Procedure[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selectedVersion, setSelectedVersion] = useState("latest");
  const [selectedProcedure, setSelectedProcedure] = useState<ProcedureDetail | null>(null);
  const [loadingProcedures, setLoadingProcedures] = useState(true);
  const [loadingBuilder, setLoadingBuilder] = useState(false);
  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const [error, setError] = useState("");
  const [procPage, setProcPage] = useState(0);
  const [recentProcedures, setRecentProcedures] = useState<RecentProcedureEntry[]>([]);
  const [lastSession, setLastSession] = useState<RecentProcedureEntry | null>(null);

  const procedureQuery = searchParams.get("procedure") ?? "";
  const versionQuery = searchParams.get("version") ?? "latest";

  useEffect(() => {
    setRecentProcedures(readRecentProcedures());
    setLastSession(readLastBuilderSession());
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadProcedures() {
      setLoadingProcedures(true);
      try {
        const items = await listProcedures();
        if (!cancelled) {
          setProcedures(items);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load procedures");
        }
      } finally {
        if (!cancelled) {
          setLoadingProcedures(false);
        }
      }
    }

    void loadProcedures();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!procedureQuery) {
      setSelectedId("");
      setSelectedVersion("latest");
      setSelectedProcedure(null);
      setVersions([]);
      return;
    }

    let cancelled = false;

    async function loadSelection() {
      setLoadingBuilder(true);
      setError("");
      try {
        const [detail, versionList] = await Promise.all([
          getProcedure(procedureQuery, versionQuery === "latest" ? undefined : versionQuery),
          listVersions(procedureQuery),
        ]);
        if (!cancelled) {
          setSelectedId(procedureQuery);
          setSelectedVersion(versionQuery);
          setSelectedProcedure(detail);
          setVersions(versionList);
        }
      } catch (err) {
        if (!cancelled) {
          setSelectedProcedure(null);
          setVersions([]);
          setError(err instanceof Error ? err.message : "Could not load selected procedure");
        }
      } finally {
        if (!cancelled) {
          setLoadingBuilder(false);
        }
      }
    }

    void loadSelection();
    return () => {
      cancelled = true;
    };
  }, [procedureQuery, versionQuery]);

  useEffect(() => {
    if (!selectedProcedure) return;

    const entry: RecentProcedureEntry = {
      procedureId: selectedProcedure.procedure_id,
      version: selectedProcedure.version,
      name: selectedProcedure.name,
      description: selectedProcedure.description ?? "",
      status: selectedProcedure.status ?? "unknown",
      openedAt: new Date().toISOString(),
    };

    setRecentProcedures((current) => {
      const next = [
        entry,
        ...current.filter(
          (item) => !(item.procedureId === entry.procedureId && item.version === entry.version),
        ),
      ].slice(0, MAX_RECENT_PROCEDURES);
      writeRecentProcedures(next);
      return next;
    });
    setLastSession(entry);
    writeLastBuilderSession(entry);
  }, [selectedProcedure]);

  const pagedProcedures = useMemo(
    () => procedures.slice(procPage * PROCEDURE_PAGE_SIZE, (procPage + 1) * PROCEDURE_PAGE_SIZE),
    [procedures, procPage],
  );

  function syncQuery(id: string, version: string) {
    const next = new URLSearchParams();
    if (id) {
      next.set("procedure", id);
      next.set("version", version);
    }
    const query = next.toString();
    router.replace(query ? `/builder?${query}` : "/builder");
  }

  function handleProcedureChange(id: string) {
    setProcPage(0);
    if (!id) {
      syncQuery("", "latest");
      return;
    }
    syncQuery(id, "latest");
  }

  function handleVersionChange(version: string) {
    if (!selectedId) return;
    syncQuery(selectedId, version);
  }

  function handleOpenRecent(entry: RecentProcedureEntry) {
    syncQuery(entry.procedureId, entry.version || "latest");
  }

  async function handleSaveWorkflow(workflowGraph: CkpWorkflowGraph) {
    if (!selectedProcedure) return;

    setSavingWorkflow(true);
    try {
      const updatedCkp = {
        ...(selectedProcedure.ckp_json as Record<string, unknown>),
        workflow_graph: workflowGraph,
      };
      await updateProcedure(selectedProcedure.procedure_id, selectedProcedure.version, updatedCkp);
      const [refreshed, versionList] = await Promise.all([
        getProcedure(selectedProcedure.procedure_id, selectedProcedure.version),
        listVersions(selectedProcedure.procedure_id),
      ]);
      setSelectedProcedure(refreshed);
      setVersions(versionList);
      toast("Workflow saved successfully", "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to save workflow", "error");
    } finally {
      setSavingWorkflow(false);
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-4rem)] flex-col bg-neutral-50">
      <div className="px-6 pt-6">
        <section className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
          <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-neutral-400">Automation Workspace</p>
            <h1 className="mt-1 text-2xl font-semibold text-neutral-900 dark:text-neutral-100">Visual Builder</h1>
            <p className="mt-1 max-w-3xl text-sm text-neutral-500 dark:text-neutral-400">
              This is the single workflow editing surface now. Procedures launch here instead of embedding a cramped builder inside the detail page.
            </p>
          </div>
          {selectedProcedure && (
            <Link
              href={`/procedures/${encodeURIComponent(selectedProcedure.procedure_id)}/${encodeURIComponent(selectedProcedure.version)}`}
              className="inline-flex items-center rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 transition hover:border-neutral-400 hover:bg-neutral-50"
            >
              Back to Procedure
            </Link>
          )}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
          <select
            value={selectedId}
            onChange={(e) => handleProcedureChange(e.target.value)}
            aria-label="Select procedure"
            className="min-w-60 rounded-2xl border border-neutral-300 bg-white px-4 py-2 text-sm text-neutral-800 shadow-sm outline-none transition focus:border-sky-500"
          >
            <option value="">Select a procedure...</option>
            {procedures.map((procedure) => (
              <option key={procedure.procedure_id} value={procedure.procedure_id}>
                {procedure.name}
              </option>
            ))}
          </select>

          <select
            value={selectedVersion}
            onChange={(e) => handleVersionChange(e.target.value)}
            aria-label="Select version"
            disabled={!selectedId}
            className="min-w-40 rounded-2xl border border-neutral-300 bg-white px-4 py-2 text-sm text-neutral-800 shadow-sm outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="latest">Latest version</option>
            {versions.map((version) => (
              <option key={version.version} value={version.version}>
                v{version.version}
              </option>
            ))}
          </select>

          {selectedId && (
            <button
              onClick={() => syncQuery(selectedId, selectedVersion)}
              className="rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 transition hover:border-neutral-400 hover:bg-neutral-50"
            >
              Refresh
            </button>
          )}
          </div>
        </section>
      </div>

      {error && (
        <div className="mx-6 mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {!selectedProcedure && !loadingBuilder && (
        <div className="flex flex-1 flex-col px-6 py-6">
          <div className="rounded-2xl border border-neutral-200 bg-white p-8 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <div className="max-w-2xl">
              <p className="text-sm font-semibold uppercase tracking-[0.2em] text-neutral-500 dark:text-neutral-400">Builder First</p>
              <h2 className="mt-3 text-3xl font-semibold text-neutral-900 dark:text-neutral-100">Choose a procedure and edit it in the dedicated canvas workspace.</h2>
              <p className="mt-3 text-sm leading-6 text-neutral-600 dark:text-neutral-400">
                The old graph viewer has been retired from this route. This page now owns the full editing workflow, saving directly back into the procedure version you select.
              </p>
            </div>

            {(lastSession || recentProcedures.length > 0) && (
              <div className="mt-8 grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
                <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-800/40">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-500 dark:text-neutral-400">Resume</p>
                  {lastSession ? (
                    <>
                      <h3 className="mt-2 text-lg font-semibold text-neutral-900 dark:text-neutral-100">Continue your last builder session</h3>
                      <div className="mt-4 rounded-2xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-neutral-900 dark:text-neutral-100">{lastSession.name}</p>
                            <p className="mt-1 truncate text-xs text-neutral-500 dark:text-neutral-400">{lastSession.procedureId}</p>
                          </div>
                          <span className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${statusClass(lastSession.status)}`}>
                            {lastSession.status}
                          </span>
                        </div>
                        <p className="mt-3 line-clamp-2 text-xs leading-5 text-neutral-500 dark:text-neutral-400">
                          {lastSession.description || "No description provided."}
                        </p>
                        <div className="mt-4 flex items-center justify-between gap-3">
                          <span className="text-xs text-neutral-400 dark:text-neutral-500">
                            Last opened {new Date(lastSession.openedAt).toLocaleString()}
                          </span>
                          <button
                            onClick={() => handleOpenRecent(lastSession)}
                            className="rounded-full bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700"
                          >
                            Resume
                          </button>
                        </div>
                      </div>
                    </>
                  ) : null}
                </div>

                <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-500 dark:text-neutral-400">Recent Procedures</p>
                  <div className="mt-4 space-y-3">
                    {recentProcedures.length > 0 ? (
                      recentProcedures.map((entry) => (
                        <button
                          key={`${entry.procedureId}-${entry.version}`}
                          onClick={() => handleOpenRecent(entry)}
                          className="flex w-full items-start justify-between gap-3 rounded-2xl border border-neutral-200 bg-white px-4 py-3 text-left transition hover:border-sky-300 hover:bg-sky-50/50 dark:border-neutral-800 dark:bg-neutral-900"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-neutral-900 dark:text-neutral-100">{entry.name}</p>
                            <p className="mt-1 truncate text-xs text-neutral-500 dark:text-neutral-400">{entry.procedureId} · v{entry.version}</p>
                          </div>
                          <span className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${statusClass(entry.status)}`}>
                            {entry.status}
                          </span>
                        </button>
                      ))
                    ) : (
                      <p className="text-sm text-neutral-500 dark:text-neutral-400">Your recent builder sessions will appear here.</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            <div className="mt-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {pagedProcedures.map((procedure) => (
                <button
                  key={procedure.procedure_id}
                  onClick={() => handleProcedureChange(procedure.procedure_id)}
                  className="rounded-2xl border border-neutral-200 bg-white px-4 py-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-md dark:border-neutral-800 dark:bg-neutral-900"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-neutral-900 dark:text-neutral-100">{procedure.name}</p>
                      <p className="mt-1 truncate text-xs text-neutral-500 dark:text-neutral-400">{procedure.procedure_id}</p>
                    </div>
                    <span className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${statusClass(procedure.status)}`}>
                      {procedure.status ?? "unknown"}
                    </span>
                  </div>
                  {procedure.description && (
                    <p className="mt-3 line-clamp-2 text-xs leading-5 text-neutral-500 dark:text-neutral-400">{procedure.description}</p>
                  )}
                </button>
              ))}
            </div>

            {procedures.length > PROCEDURE_PAGE_SIZE && (
              <div className="mt-5 flex items-center justify-center gap-3">
                <button
                  onClick={() => setProcPage((page) => Math.max(0, page - 1))}
                  disabled={procPage === 0}
                  className="rounded-full border border-neutral-300 px-4 py-2 text-xs font-medium text-neutral-600 disabled:opacity-40 dark:border-neutral-700 dark:text-neutral-300"
                >
                  Previous
                </button>
                <span className="text-xs text-neutral-500 dark:text-neutral-400">
                  Page {procPage + 1} of {Math.ceil(procedures.length / PROCEDURE_PAGE_SIZE)}
                </span>
                <button
                  onClick={() => setProcPage((page) => page + 1)}
                  disabled={(procPage + 1) * PROCEDURE_PAGE_SIZE >= procedures.length}
                  className="rounded-full border border-neutral-300 px-4 py-2 text-xs font-medium text-neutral-600 disabled:opacity-40 dark:border-neutral-700 dark:text-neutral-300"
                >
                  Next
                </button>
              </div>
            )}

            {loadingProcedures && (
              <p className="mt-4 text-sm text-neutral-500 dark:text-neutral-400">Loading procedures...</p>
            )}
          </div>
        </div>
      )}

      {loadingBuilder && (
        <div className="flex flex-1 items-center justify-center px-6 py-10">
          <div className="flex items-center gap-3 rounded-full border border-neutral-200 bg-white px-5 py-3 text-sm text-neutral-600 shadow-sm dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-300">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-sky-600 border-t-transparent" />
            Loading builder workspace...
          </div>
        </div>
      )}

      {selectedProcedure && !loadingBuilder && (
        <div className="flex flex-1 flex-col px-6 py-6">
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">{selectedProcedure.name}</h2>
                <span className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${statusClass(selectedProcedure.status)}`}>
                  {selectedProcedure.status ?? "unknown"}
                </span>
                <span className="rounded-full bg-neutral-100 px-2 py-1 text-[10px] font-semibold uppercase text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                  v{selectedProcedure.version}
                </span>
              </div>
              <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">{selectedProcedure.description || "No procedure description provided."}</p>
            </div>
            <Link
              href={`/procedures/${encodeURIComponent(selectedProcedure.procedure_id)}/${encodeURIComponent(selectedProcedure.version)}?tab=graph`}
              className="rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 transition hover:border-neutral-400 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
            >
              View Procedure Detail
            </Link>
          </div>

          <div className="min-h-0 flex-1 overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <WorkflowBuilderV2Wrapper
              key={`${selectedProcedure.procedure_id}-${selectedProcedure.version}`}
              procedureId={selectedProcedure.procedure_id}
              procedureVersion={selectedProcedure.version}
              baseCkpJson={selectedProcedure.ckp_json as Record<string, unknown>}
              initialWorkflowGraph={((selectedProcedure.ckp_json as Record<string, unknown>)?.workflow_graph as Record<string, unknown> | null) ?? null}
              initialBuilderDraft={selectedProcedure.builder_draft}
              initialBuilderDraftUpdatedAt={selectedProcedure.builder_draft_updated_at}
              onSaveWorkflow={handleSaveWorkflow}
              savingWorkflow={savingWorkflow}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export default function BuilderPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-neutral-50 px-6 py-10">
          <div className="flex items-center gap-3 rounded-full border border-neutral-200 bg-white px-5 py-3 text-sm text-neutral-600 shadow-sm dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-300">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-sky-600 border-t-transparent" />
            Loading builder workspace...
          </div>
        </div>
      }
    >
      <BuilderPageContent />
    </Suspense>
  );
}


