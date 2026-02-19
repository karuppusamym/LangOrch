"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { listProcedures, importProcedure, listProjects, createRun } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ProcedureStatusBadge as StatusBadge } from "@/components/shared/ProcedureStatusBadge";
import type { Procedure, Project } from "@/lib/types";

export default function ProceduresPage() {
  const { toast } = useToast();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [projects, setProjects]     = useState<Project[]>([]);
  const [loading, setLoading]       = useState(true);
  const [showImport, setShowImport] = useState(false);
  const [importJson, setImportJson] = useState("");
  const [importProjectId, setImportProjectId] = useState("");
  const [importError, setImportError] = useState("");
  const [search, setSearch]         = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState(searchParams.get("project_id") ?? "");
  const [runningId, setRunningId]   = useState<string | null>(null);

  useEffect(() => {
    const pid = searchParams.get("project_id") ?? "";
    setProjectFilter(pid);
  }, [searchParams]);

  const loadProcedures = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (statusFilter)  params.status     = statusFilter;
      if (projectFilter) params.project_id = projectFilter;
      const data = await listProcedures(Object.keys(params).length ? params : undefined);
      setProcedures(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, projectFilter]);

  useEffect(() => { void loadProcedures(); }, [loadProcedures]);
  useEffect(() => { listProjects().then(setProjects).catch(() => {}); }, []);

  function changeProjectFilter(val: string) {
    setProjectFilter(val);
    const url = new URL(window.location.href);
    if (val) url.searchParams.set("project_id", val);
    else     url.searchParams.delete("project_id");
    router.replace(url.pathname + url.search);
  }

  async function handleQuickRun(proc: Procedure, e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const key = `${proc.procedure_id}:${proc.version}`;
    setRunningId(key);
    try {
      const run = await createRun(proc.procedure_id, proc.version);
      toast(`Run started: ${run.run_id.slice(0, 8)}…`, "success");
      router.push("/runs");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to start run", "error");
    } finally {
      setRunningId(null);
    }
  }

  async function handleImport() {
    setImportError("");
    try {
      const parsed = JSON.parse(importJson);
      await importProcedure(parsed, importProjectId || undefined);
      setShowImport(false);
      setImportJson("");
      setImportProjectId("");
      toast("Procedure imported successfully", "success");
      void loadProcedures();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Invalid JSON";
      setImportError(msg);
      toast(`Import failed: ${msg}`, "error");
    }
  }

  const activeProject = projects.find((p) => p.project_id === projectFilter);
  const filtered = procedures.filter((proc) =>
    !search ||
    proc.name.toLowerCase().includes(search.toLowerCase()) ||
    proc.procedure_id.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Breadcrumb when filtered by project */}
      {activeProject && (
        <div className="flex items-center gap-2 text-sm">
          <button
            onClick={() => changeProjectFilter("")}
            className="text-gray-400 hover:text-gray-600 hover:underline"
          >
            All Procedures
          </button>
          <span className="text-gray-300">/</span>
          <span className="font-medium text-gray-700">{activeProject.name}</span>
          <span className="ml-1 rounded-full bg-primary-100 px-2 py-0.5 text-xs text-primary-700">
            {procedures.length} procedure{procedures.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}

      {/* Actions bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search procedures…"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none w-52"
          />
          <select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="draft">Draft</option>
            <option value="deprecated">Deprecated</option>
            <option value="archived">Archived</option>
          </select>
          <select
            aria-label="Filter by project"
            value={projectFilter}
            onChange={(e) => changeProjectFilter(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
          >
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.project_id} value={p.project_id}>{p.name}</option>
            ))}
          </select>
          <p className="text-sm text-gray-400">
            {filtered.length}{filtered.length !== procedures.length ? ` of ${procedures.length}` : ""} procedure{procedures.length !== 1 ? "s" : ""}
          </p>
        </div>
        <button
          onClick={() => setShowImport(true)}
          className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 shrink-0"
        >
          Import CKP
        </button>
      </div>

      {/* Import dialog */}
      {showImport && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold">Paste CKP JSON</h3>
          <textarea
            value={importJson}
            onChange={(e) => setImportJson(e.target.value)}
            className="h-48 w-full rounded-lg border border-gray-300 p-3 font-mono text-xs focus:border-primary-500 focus:outline-none"
            placeholder='{"procedure_id": "...", "version": "...", ...}'
          />
          {projects.length > 0 && (
            <div className="mt-3">
              <label className="mb-1 block text-xs text-gray-500">Assign to project (optional)</label>
              <select
                aria-label="Assign to project"
                value={importProjectId}
                onChange={(e) => setImportProjectId(e.target.value)}
                className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
              >
                <option value="">— No project —</option>
                {projects.map((p) => (
                  <option key={p.project_id} value={p.project_id}>{p.name}</option>
                ))}
              </select>
            </div>
          )}
          {importError && <p className="mt-2 text-sm text-red-600">{importError}</p>}
          <div className="mt-3 flex gap-2">
            <button
              onClick={handleImport}
              className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
            >
              Import
            </button>
            <button
              onClick={() => { setShowImport(false); setImportError(""); setImportProjectId(""); }}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Procedure list */}
      {loading ? (
        <p className="text-gray-500">Loading...</p>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 p-12 text-center text-gray-400">
          {procedures.length === 0
            ? 'No procedures imported yet. Click "Import CKP" to get started.'
            : "No procedures match your current filters."}
        </div>
      ) : (
        <div className="grid gap-3">
          {filtered.map((proc) => {
            const key = `${proc.procedure_id}:${proc.version}`;
            const href = `/procedures/${encodeURIComponent(proc.procedure_id)}/${encodeURIComponent(proc.version)}`;
            const projName = projects.find((p) => p.project_id === proc.project_id)?.name;
            const isRunning = runningId === key;

            return (
              <div
                key={key}
                className="flex items-stretch rounded-xl border border-gray-200 bg-white shadow-sm transition hover:shadow-md"
              >
                {/* Main content — click through to detail */}
                <Link href={href} className="flex min-w-0 flex-1 flex-col justify-center gap-1 px-5 py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-medium text-gray-900">{proc.name}</h3>
                    <StatusBadge status={proc.status} />
                    {projName && (
                      <span className="rounded-full border border-primary-200 bg-primary-50 px-2 py-0.5 text-xs text-primary-700">
                        {projName}
                      </span>
                    )}
                  </div>
                  {proc.description && (
                    <p className="truncate text-sm text-gray-500">{proc.description}</p>
                  )}
                  <p className="text-xs text-gray-400">
                    {proc.procedure_id} · v{proc.version}
                    {proc.effective_date && <span className="ml-2">· Effective: {proc.effective_date}</span>}
                  </p>
                </Link>

                {/* Action buttons — stop propagation so they don't navigate */}
                <div className="flex shrink-0 items-center gap-2 border-l border-gray-100 px-4">
                  <button
                    onClick={(e) => void handleQuickRun(proc, e)}
                    disabled={isRunning || proc.status === "archived" || proc.status === "deprecated"}
                    title={isRunning ? "Starting…" : "Run with default inputs"}
                    className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
                  >
                    {isRunning ? "Starting…" : "▶ Run"}
                  </button>
                  <Link
                    href={`${href}?tab=graph`}
                    onClick={(e) => e.stopPropagation()}
                    className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 whitespace-nowrap"
                  >
                    Graph
                  </Link>
                  <Link
                    href={`${href}?tab=explain`}
                    onClick={(e) => e.stopPropagation()}
                    className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 whitespace-nowrap"
                  >
                    Analyze
                  </Link>
                  <span className="hidden text-xs text-gray-300 xl:block">
                    {new Date(proc.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
