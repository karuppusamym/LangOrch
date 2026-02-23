"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { listProcedures, importProcedure, listProjects, createRun, getProcedure } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ProcedureStatusBadge as StatusBadge } from "@/components/shared/ProcedureStatusBadge";
import { flattenVariablesSchema, isFieldSensitive } from "@/lib/redact";
import type { Procedure, Project, ProcedureDetail } from "@/lib/types";

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

  // ── Quick-run modal state ──────────────────────────────────────
  const [quickRunProc, setQuickRunProc]         = useState<ProcedureDetail | null>(null);
  const [showVarsModal, setShowVarsModal]       = useState(false);
  const [varsForm, setVarsForm]                 = useState<Record<string, string>>({});
  const [varsErrors, setVarsErrors]             = useState<Record<string, string>>({});
  const [runCreating, setRunCreating]           = useState(false);

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
      // Fetch full CKP to check for required variables
      const detail = await getProcedure(proc.procedure_id, proc.version);
      const schema = flattenVariablesSchema(
        (detail.ckp_json as any)?.variables_schema ?? {}
      );
      const entries = Object.entries(schema) as [string, any][];
      if (entries.length > 0) {
        // Pre-fill defaults, then show modal
        const defaults: Record<string, string> = {};
        entries.forEach(([k, v]) => {
          defaults[k] = v?.default !== undefined ? String(v.default) : "";
        });
        if (proc.status === "draft") {
          toast("Warning: this procedure is in DRAFT status.", "info");
        }
        setQuickRunProc(detail);
        setVarsForm(defaults);
        setVarsErrors({});
        setShowVarsModal(true);
      } else {
        // No variables — run immediately
        const run = await createRun(proc.procedure_id, proc.version);
        toast(`Run started: ${run.run_id.slice(0, 8)}…`, "success");
        router.push("/runs");
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to start run", "error");
    } finally {
      setRunningId(null);
    }
  }

  async function doQuickCreateRun(vars: Record<string, unknown>) {
    if (!quickRunProc) return;
    setRunCreating(true);
    try {
      const run = await createRun(quickRunProc.procedure_id, quickRunProc.version, vars);
      toast(`Run started: ${run.run_id.slice(0, 8)}…`, "success");
      setShowVarsModal(false);
      router.push("/runs");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to start run", "error");
    } finally {
      setRunCreating(false);
    }
  }

  function handleVarChange(key: string, value: string, meta: Record<string, any>) {
    setVarsForm((prev) => ({ ...prev, [key]: value }));
    const err = validateVarField(key, value, meta);
    setVarsErrors((prev) => {
      const next = { ...prev };
      if (err) next[key] = err;
      else delete next[key];
      return next;
    });
  }

  function validateVarField(key: string, raw: string, meta: Record<string, any>): string {
    if (meta?.required && !raw.trim()) return "This field is required";
    if (!raw) return "";
    const validation = (meta?.validation ?? {}) as Record<string, any>;
    if (validation.regex) {
      try {
        if (!new RegExp(`^(?:${validation.regex as string})$`).test(raw))
          return `Must match pattern: ${validation.regex as string}`;
      } catch { /* skip */ }
    }
    const vtype = (meta?.type ?? "string") as string;
    if (vtype === "number") {
      const num = Number(raw);
      if (validation.min !== undefined && num < (validation.min as number))
        return `Min: ${validation.min as number}`;
      if (validation.max !== undefined && num > (validation.max as number))
        return `Max: ${validation.max as number}`;
    }
    const allowed = validation.allowed_values as string[] | undefined;
    if (allowed && !allowed.includes(raw)) return `Must be one of: ${allowed.join(", ")}`;
    return "";
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
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">Procedures</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">
            {activeProject ? `Showing procedures for: ${activeProject.name}` : "Manage and run your workflow procedures"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {activeProject && (
            <button onClick={() => changeProjectFilter("")}
              className="rounded-lg border border-neutral-300 dark:border-neutral-700 px-3 py-2 text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800">
              ← All Procedures
            </button>
          )}
          <button onClick={() => setShowImport(true)}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" /></svg>
            Import CKP
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[180px]">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search procedures…"
              className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 pl-9 pr-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
          </div>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status"
            className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 focus:border-blue-500 focus:outline-none">
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="draft">Draft</option>
            <option value="deprecated">Deprecated</option>
            <option value="archived">Archived</option>
          </select>
          <select value={projectFilter} onChange={(e) => changeProjectFilter(e.target.value)} aria-label="Filter by project"
            className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 focus:border-blue-500 focus:outline-none">
            <option value="">All Projects</option>
            {projects.map((p) => (<option key={p.project_id} value={p.project_id}>{p.name}</option>))}
          </select>
          <span className="text-xs text-neutral-400">{filtered.length}{filtered.length !== procedures.length ? ` of ${procedures.length}` : ""} procedure{procedures.length !== 1 ? "s" : ""}</span>
        </div>
      </div>

      {/* Import form */}
      {showImport && (
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-6 shadow-sm">
          <h3 className="mb-3 text-base font-semibold text-neutral-900 dark:text-neutral-100">Import CKP Procedure</h3>
          <textarea value={importJson} onChange={(e) => setImportJson(e.target.value)}
            className="h-48 w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 p-3 font-mono text-xs focus:border-blue-500 focus:outline-none"
            placeholder='{"procedure_id": "...", "version": "...", ...}' />
          {projects.length > 0 && (
            <div className="mt-3">
              <label className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Assign to project (optional)</label>
              <select value={importProjectId} onChange={(e) => setImportProjectId(e.target.value)} aria-label="Assign to project"
                className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none">
                <option value="">— No project —</option>
                {projects.map((p) => (<option key={p.project_id} value={p.project_id}>{p.name}</option>))}
              </select>
            </div>
          )}
          {importError && <p className="mt-2 text-sm text-red-600">{importError}</p>}
          <div className="mt-3 flex gap-2">
            <button onClick={handleImport} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">Import</button>
            <button onClick={() => { setShowImport(false); setImportError(""); setImportProjectId(""); }}
              className="rounded-lg border border-neutral-300 dark:border-neutral-700 px-4 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Procedure table */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 p-16 text-center text-neutral-400">
          {procedures.length === 0 ? 'No procedures yet. Click "Import CKP" to get started.' : "No procedures match your current filters."}
        </div>
      ) : (
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-800/50 border-b border-neutral-200 dark:border-neutral-700">
              <tr className="text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                <th className="px-5 py-3">Name</th>
                <th className="px-5 py-3">Version</th>
                <th className="px-5 py-3">Project</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3">Created</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {filtered.map((proc) => {
                const key = `${proc.procedure_id}:${proc.version}`;
                const href = `/procedures/${encodeURIComponent(proc.procedure_id)}/${encodeURIComponent(proc.version)}`;
                const projName = projects.find((p) => p.project_id === proc.project_id)?.name;
                const isRunning = runningId === key;
                return (
                  <tr key={key} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/50 transition-colors">
                    <td className="px-5 py-3">
                      <Link href={href} className="font-medium text-neutral-900 dark:text-neutral-100 hover:text-blue-600 dark:hover:text-blue-400">
                        {proc.name}
                      </Link>
                      {proc.description && <p className="text-xs text-neutral-400 mt-0.5 truncate max-w-[250px]">{proc.description}</p>}
                    </td>
                    <td className="px-5 py-3">
                      <span className="rounded-md bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 text-xs font-mono text-neutral-600 dark:text-neutral-400">v{proc.version}</span>
                    </td>
                    <td className="px-5 py-3">
                      {projName ? (
                        <span className="rounded-full bg-blue-50 dark:bg-blue-950/50 border border-blue-200 dark:border-blue-800 px-2 py-0.5 text-xs text-blue-700 dark:text-blue-400">{projName}</span>
                      ) : (
                        <span className="text-xs text-neutral-400">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      <StatusBadge status={proc.status} />
                    </td>
                    <td className="px-5 py-3 text-xs text-neutral-400">{new Date(proc.created_at).toLocaleDateString()}</td>
                    <td className="px-5 py-3">
                      <div className="flex items-center justify-end gap-1.5">
                        <button onClick={(e) => void handleQuickRun(proc, e)}
                          disabled={isRunning || proc.status === "archived" || proc.status === "deprecated"}
                          className="flex items-center gap-1 rounded-md bg-blue-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed">
                          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
                          {isRunning ? "Starting…" : "Run"}
                        </button>
                        <Link href={`${href}?tab=graph`} onClick={(e) => e.stopPropagation()}
                          className="rounded-md border border-neutral-200 dark:border-neutral-700 px-2.5 py-1.5 text-xs font-medium text-neutral-600 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800">
                          Graph
                        </Link>
                        <Link href={`${href}?tab=explain`} onClick={(e) => e.stopPropagation()}
                          className="rounded-md border border-neutral-200 dark:border-neutral-700 px-2.5 py-1.5 text-xs font-medium text-neutral-600 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800">
                          Analyze
                        </Link>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Quick-run variables modal ──────────────────────────── */}
      {showVarsModal && quickRunProc && (() => {
        const schema = flattenVariablesSchema(
          (quickRunProc.ckp_json as any)?.variables_schema ?? {}
        );
        const schemaEntries = Object.entries(schema) as [string, any][];
        const mustFillEntries = schemaEntries.filter(
          ([, meta]) => !!(meta as any)?.required && (meta as any)?.default === undefined
        );
        const overrideEntries = schemaEntries.filter(
          ([, meta]) => !(meta as any)?.required || (meta as any)?.default !== undefined
        );

        function fieldRow(key: string, meta: Record<string, any>, showDefault = false) {
          const validation = (meta?.validation ?? {}) as Record<string, any>;
          const allowed = validation.allowed_values as string[] | undefined;
          const isRequired = !!meta?.required;
          const hasDefault = meta?.default !== undefined;
          const isSensitive = isFieldSensitive(meta as Record<string, unknown>);
          const currentVal = varsForm[key] ?? "";
          const isUsingDefault = hasDefault && currentVal === String(meta.default);
          const fieldErr = varsErrors[key];
          const borderCls = fieldErr
            ? "border-red-400 focus:border-red-500"
            : showDefault && isUsingDefault
            ? "border-gray-200 bg-gray-50 focus:border-primary-500 focus:bg-white"
            : "border-gray-300 focus:border-primary-500";
          return (
            <div key={key}>
              <div className="mb-1 flex flex-wrap items-baseline gap-x-2">
                <label className="text-xs font-semibold text-gray-700">
                  {key}{isRequired && <span className="ml-0.5 text-red-500">*</span>}
                </label>
                {meta?.type && <span className="text-[10px] uppercase tracking-wide text-gray-400">{meta.type as string}</span>}
                {isSensitive && <span className="text-[10px] text-yellow-600 font-medium">🔒 sensitive</span>}
                {showDefault && hasDefault && !isSensitive && (
                  <span className="ml-auto text-[10px] text-gray-400">
                    default: <code className="font-mono">{String(meta.default)}</code>
                    {!isUsingDefault && (
                      <button type="button" onClick={() => handleVarChange(key, String(meta.default), meta)} className="ml-1 text-primary-600 hover:underline">restore</button>
                    )}
                  </span>
                )}
              </div>
              {meta?.description && <p className="mb-1.5 text-xs text-gray-400">{meta.description as string}</p>}
              {allowed ? (
                <select aria-label={key} value={currentVal} onChange={(e) => handleVarChange(key, e.target.value, meta)} className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}>
                  <option value="">— select —</option>
                  {allowed.map((v: string) => <option key={v} value={v}>{v}</option>)}
                </select>
              ) : meta?.type === "array" || meta?.type === "object" ? (
                <textarea value={currentVal} onChange={(e) => handleVarChange(key, e.target.value, meta)} placeholder={meta?.type === "array" ? '["item1","item2"]' : '{"key":"value"}'} rows={3} className={`w-full rounded-lg border p-2 font-mono text-sm focus:outline-none ${borderCls}`} />
              ) : (
                <input
                  type={isSensitive ? "password" : meta?.type === "number" ? "number" : "text"}
                  value={currentVal}
                  onChange={(e) => handleVarChange(key, e.target.value, meta)}
                  placeholder={hasDefault && !isSensitive ? String(meta.default) : ""}
                  autoComplete="off"
                  className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}
                />
              )}
              {fieldErr && <p className="mt-1 text-xs text-red-500">{fieldErr}</p>}
            </div>
          );
        }

        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
            <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
              <h3 className="mb-0.5 text-base font-semibold text-gray-900">
                {mustFillEntries.length > 0
                  ? `${mustFillEntries.length} required field${mustFillEntries.length !== 1 ? "s" : ""} need input`
                  : "Review Run Variables"}
              </h3>
              <p className="mb-1 text-xs text-gray-500 font-medium">{quickRunProc.name}</p>
              <p className="mb-4 text-xs text-gray-400">
                {mustFillEntries.length > 0
                  ? "Fill in the required fields before starting."
                  : "All fields have default values. Override any before starting."}
              </p>
              <div className="max-h-[60vh] overflow-y-auto space-y-4 pr-1">
                {mustFillEntries.map(([key, meta]) => fieldRow(key, meta, false))}
                {overrideEntries.length > 0 && (
                  mustFillEntries.length > 0 ? (
                    <details className="group">
                      <summary className="flex cursor-pointer select-none list-none items-center gap-1 py-2 text-xs font-medium text-gray-500 hover:text-gray-700">
                        <span className="inline-block transition-transform group-open:rotate-90">▶</span>
                        {`${overrideEntries.length} field${overrideEntries.length !== 1 ? "s" : ""} have defaults — expand to override`}
                      </summary>
                      <div className="space-y-4 mt-3">
                        {overrideEntries.map(([key, meta]) => fieldRow(key, meta, true))}
                      </div>
                    </details>
                  ) : (
                    <div className="space-y-4">
                      {overrideEntries.map(([key, meta]) => fieldRow(key, meta, true))}
                    </div>
                  )
                )}
              </div>
              <div className="mt-5 flex gap-2">
                <button
                  onClick={() => {
                    const allErrors: Record<string, string> = {};
                    schemaEntries.forEach(([k, meta]) => {
                      const e = validateVarField(k, varsForm[k] ?? "", meta);
                      if (e) allErrors[k] = e;
                    });
                    if (Object.keys(allErrors).length > 0) { setVarsErrors(allErrors); return; }
                    const parsed: Record<string, unknown> = {};
                    let parseError = false;
                    schemaEntries.forEach(([k, meta]) => {
                      const raw = varsForm[k];
                      if (meta?.type === "array" || meta?.type === "object") {
                        if (!raw) return; // blank optional field — omit
                        try { parsed[k] = JSON.parse(raw); }
                        catch { toast(`Invalid JSON for "${k}" — expected ${meta.type === "array" ? "[...]" : "{...}"}`, "error"); parseError = true; }
                      } else {
                        parsed[k] = meta?.type === "number" ? Number(raw) : raw;
                      }
                    });
                    if (parseError) return;
                    void doQuickCreateRun(parsed);
                  }}
                  disabled={runCreating || Object.keys(varsErrors).length > 0}
                  className="flex-1 rounded-lg bg-green-600 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
                >
                  {runCreating ? "Starting…" : "Start Run"}
                </button>
                <button
                  onClick={() => setShowVarsModal(false)}
                  className="flex-1 rounded-lg border border-gray-300 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
