"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listProcedures, importProcedure, listProjects } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ProcedureStatusBadge as StatusBadge } from "@/components/shared/ProcedureStatusBadge";
import type { Procedure, Project } from "@/lib/types";

export default function ProceduresPage() {
  const { toast } = useToast();
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [projects, setProjects]     = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showImport, setShowImport] = useState(false);
  const [importJson, setImportJson] = useState("");
  const [importProjectId, setImportProjectId] = useState("");
  const [importError, setImportError] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState("");

  useEffect(() => {
    loadProcedures();
  }, [statusFilter, projectFilter]);

  useEffect(() => {
    listProjects().then(setProjects).catch(() => {});
  }, []);

  async function loadProcedures() {
    try {
      const params: Record<string, string> = {};
      if (statusFilter) params.status = statusFilter;
      if (projectFilter) params.project_id = projectFilter;
      const data = await listProcedures(Object.keys(params).length ? params : undefined);
      setProcedures(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
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
      loadProcedures();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Invalid JSON";
      setImportError(msg);
      toast(`Import failed: ${msg}`, "error");
    }
  }

  return (
    <div className="space-y-6">
      {/* Actions bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search procedures…"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none w-56"
          />
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setLoading(true); }}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="draft">Draft</option>
            <option value="deprecated">Deprecated</option>
            <option value="archived">Archived</option>
          </select>
          <select
            value={projectFilter}
            onChange={(e) => { setProjectFilter(e.target.value); setLoading(true); }}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
          >
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.project_id} value={p.project_id}>{p.name}</option>
            ))}
          </select>
          <p className="text-sm text-gray-400">
            {procedures.filter(p =>
              !search || p.name.toLowerCase().includes(search.toLowerCase()) ||
              p.procedure_id.toLowerCase().includes(search.toLowerCase())
            ).length} of {procedures.length}
          </p>
        </div>
        <button
          onClick={() => setShowImport(true)}
          className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
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
      ) : procedures.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 p-12 text-center text-gray-400">
          No procedures imported yet. Click &quot;Import CKP&quot; to get started.
        </div>
      ) : (
        <div className="grid gap-4">
          {procedures
            .filter((proc) =>
              !search ||
              proc.name.toLowerCase().includes(search.toLowerCase()) ||
              proc.procedure_id.toLowerCase().includes(search.toLowerCase())
            )
            .map((proc) => (
            <Link
              key={`${proc.procedure_id}-${proc.version}`}
              href={`/procedures/${encodeURIComponent(proc.procedure_id)}/${encodeURIComponent(proc.version)}`}
              className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition hover:shadow-md"
            >
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="font-medium text-gray-900">{proc.name}</h3>
                  <StatusBadge status={proc.status} />
                </div>
                <p className="mt-1 text-sm text-gray-500">{proc.description}</p>
                <p className="mt-1 text-xs text-gray-400">
                  {proc.procedure_id} · v{proc.version}
                  {proc.effective_date && <span className="ml-2">· Effective: {proc.effective_date}</span>}
                </p>
              </div>
              <span className="text-xs text-gray-400">
                {new Date(proc.created_at).toLocaleDateString()}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
