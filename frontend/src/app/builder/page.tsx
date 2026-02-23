"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { listProcedures, listVersions, getGraph } from "@/lib/api";
import type { Procedure } from "@/lib/types";

const WorkflowGraph = dynamic(
  () => import("@/components/WorkflowGraphWrapper"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    ),
  }
);

export default function BuilderPage() {
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [versions, setVersions] = useState<Procedure[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selectedVersion, setSelectedVersion] = useState("latest");
  const [graphData, setGraphData] = useState<{ nodes: unknown[]; edges: unknown[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedProc, setSelectedProc] = useState<Procedure | null>(null);

  useEffect(() => {
    listProcedures()
      .then(setProcedures)
      .catch(() => setError("Could not load procedures"));
  }, []);

  async function loadVersionsForProc(id: string) {
    try {
      const vers = await listVersions(id);
      setVersions(vers);
      return vers;
    } catch {
      setVersions([]);
      return [];
    }
  }

  async function doLoadGraph(id: string, version: string) {
    if (!id) return;
    setLoading(true);
    setError("");
    setGraphData(null);
    try {
      const data = await getGraph(id, version);
      setGraphData(data as { nodes: unknown[]; edges: unknown[] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load graph");
    } finally {
      setLoading(false);
    }
  }

  async function onProcedureChange(id: string) {
    setSelectedId(id);
    setSelectedVersion("latest");
    setGraphData(null);
    setVersions([]);
    const proc = procedures.find((p) => p.procedure_id === id) ?? null;
    setSelectedProc(proc);
    if (!id) return;
    await loadVersionsForProc(id);
    await doLoadGraph(id, "latest");
  }

  async function onVersionChange(v: string) {
    setSelectedVersion(v);
    await doLoadGraph(selectedId, v);
  }

  // Resolve version string to actual version number (for editor link)
  const resolvedVersion =
    selectedVersion === "latest"
      ? (versions[0]?.version ?? null)
      : selectedVersion;

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      {/* ── Toolbar ──────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-4 px-6 py-3 border-b border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 shrink-0">
        <div className="min-w-0">
          <h1 className="text-lg font-bold text-neutral-900 dark:text-neutral-100 leading-tight">
            Visual Workflow Builder
          </h1>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            Inspect and explore procedure graphs — select a procedure to begin
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 ml-auto">
          {/* Procedure selector */}
          <select
            value={selectedId}
            onChange={(e) => { void onProcedureChange(e.target.value); }}
            className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none min-w-52"
          >
            <option value="">— Select procedure —</option>
            {procedures.map((p) => (
              <option key={p.procedure_id} value={p.procedure_id}>
                {p.name}
              </option>
            ))}
          </select>

          {/* Version selector */}
          {selectedId && (
            <select
              value={selectedVersion}
              onChange={(e) => { void onVersionChange(e.target.value); }}
              className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value="latest">latest</option>
              {versions.map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version}
                </option>
              ))}
            </select>
          )}

          {/* Refresh */}
          {selectedId && (
            <button
              onClick={() => { void doLoadGraph(selectedId, selectedVersion); }}
              disabled={loading}
              className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-3 py-1.5 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 disabled:opacity-50 transition-colors"
            >
              <svg className={`inline w-3.5 h-3.5 mr-1 ${loading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Refresh
            </button>
          )}

          {/* Open in Editor */}
          {selectedId && resolvedVersion && (
            <Link
              href={`/procedures/${encodeURIComponent(selectedId)}/${encodeURIComponent(resolvedVersion)}?tab=builder`}
              className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
              Open in Editor
            </Link>
          )}
        </div>
      </div>

      {/* ── Procedure meta badge ─────────────────────────────── */}
      {selectedProc && (
        <div className="px-6 py-2 border-b border-neutral-100 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900/60 flex flex-wrap items-center gap-3 text-xs text-neutral-500 dark:text-neutral-400 shrink-0">
          <span className="font-medium text-neutral-700 dark:text-neutral-300">{selectedProc.name}</span>
          <span className="font-mono">{selectedProc.procedure_id}</span>
          {selectedProc.description && (
            <span className="truncate max-w-md">{selectedProc.description}</span>
          )}
          <span className={`ml-auto rounded-full px-2 py-0.5 font-semibold ${
            selectedProc.status === "active"
              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
              : selectedProc.status === "draft"
              ? "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400"
              : "bg-neutral-100 text-neutral-600 dark:bg-neutral-800"
          }`}>
            {selectedProc.status ?? "unknown"}
          </span>
        </div>
      )}

      {/* ── Error ───────────────────────────────────────────── */}
      {error && (
        <div className="mx-6 mt-3 rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 px-4 py-2 text-sm text-red-600 dark:text-red-400 shrink-0">
          {error}
        </div>
      )}

      {/* ── Canvas ──────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden relative">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/70 dark:bg-neutral-900/70">
            <div className="flex flex-col items-center gap-3">
              <div className="h-10 w-10 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
              <p className="text-sm text-neutral-500">Loading graph…</p>
            </div>
          </div>
        )}

        {!selectedId && !loading && (
          <div className="h-full flex flex-col items-center justify-center text-neutral-400 gap-5 px-6">
            <svg className="w-20 h-20 opacity-20" fill="none" stroke="currentColor" strokeWidth={0.8} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
            </svg>
            <div className="text-center space-y-1">
              <p className="text-lg font-medium text-neutral-500 dark:text-neutral-400">Select a procedure to visualise its graph</p>
              <p className="text-sm text-neutral-400 dark:text-neutral-500">
                Use the dropdown above, then click <strong>Open in Editor</strong> to drag-and-drop edit the workflow
              </p>
            </div>
            {procedures.length > 0 && (
              <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-2 max-w-lg w-full">
                {procedures.slice(0, 6).map((p) => (
                  <button
                    key={p.procedure_id}
                    onClick={() => { void onProcedureChange(p.procedure_id); }}
                    className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-blue-50 dark:hover:bg-neutral-700 hover:border-blue-200 transition-colors text-left truncate"
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {graphData && !loading && (
          <WorkflowGraph graph={graphData as { nodes: never[]; edges: never[] }} />
        )}

        {selectedId && !loading && !graphData && !error && (
          <div className="h-full flex items-center justify-center">
            <p className="text-neutral-400 text-sm">No graph data for this procedure.</p>
          </div>
        )}
      </div>
    </div>
  );
}


