"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listProjects, createProject, updateProject, deleteProject, listProcedures } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { Project } from "@/lib/types";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [procedureCounts, setProcedureCounts] = useState<Record<string, number>>({});
  const [loading, setLoading]   = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editId, setEditId]     = useState<string | null>(null);
  const [form, setForm]         = useState({ name: "", description: "" });
  const [editForm, setEditForm] = useState({ name: "", description: "" });
  const [error, setError]       = useState("");
  const [confirmDelete, setConfirmDelete] = useState<Project | null>(null);
  const { toast } = useToast();

  useEffect(() => { void load(); }, []);

  async function load() {
    setLoading(true);
    try {
      const [projs, procs] = await Promise.all([listProjects(), listProcedures()]);
      setProjects(projs);
      const counts: Record<string, number> = {};
      for (const proc of procs) {
        if (proc.project_id) {
          counts[proc.project_id] = (counts[proc.project_id] ?? 0) + 1;
        }
      }
      setProcedureCounts(counts);
    } catch {
      toast("Failed to load projects", "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate() {
    setError("");
    if (!form.name.trim()) { setError("Name is required"); return; }
    try {
      await createProject({ name: form.name.trim(), description: form.description.trim() || undefined });
      setShowCreate(false);
      setForm({ name: "", description: "" });
      toast("Project created", "success");
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create project");
    }
  }

  async function handleUpdate(id: string) {
    if (!editForm.name.trim()) return;
    try {
      await updateProject(id, { name: editForm.name.trim(), description: editForm.description.trim() || undefined });
      setEditId(null);
      toast("Project updated", "success");
      void load();
    } catch {
      toast("Failed to update project", "error");
    }
  }

  async function handleDelete(p: Project) {
    setConfirmDelete(p);
  }

  async function doDelete() {
    if (!confirmDelete) return;
    const p = confirmDelete;
    setConfirmDelete(null);
    try {
      await deleteProject(p.project_id);
      toast("Project deleted", "success");
      void load();
    } catch {
      toast("Failed to delete project", "error");
    }
  }

  function startEdit(p: Project) {
    setEditId(p.project_id);
    setEditForm({ name: p.name, description: p.description ?? "" });
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">Projects</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">Organize procedures into projects for better management</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" /></svg>
          New Project
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-6 shadow-sm">
          <h3 className="mb-4 text-base font-semibold text-neutral-900 dark:text-neutral-100">Create Project</h3>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Name *</label>
              <input
                autoFocus
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                onKeyDown={(e) => e.key === "Enter" && void handleCreate()}
                className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 focus:border-blue-500 focus:outline-none"
                placeholder="My Project"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Description</label>
              <textarea
                rows={2}
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 focus:border-blue-500 focus:outline-none"
                placeholder="Optional description"
              />
            </div>
          </div>
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
          <div className="mt-4 flex gap-2">
            <button
              onClick={() => void handleCreate()}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              Create
            </button>
            <button
              onClick={() => { setShowCreate(false); setError(""); setForm({ name: "", description: "" }); }}
              className="rounded-lg border border-neutral-300 dark:border-neutral-700 px-4 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* List */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : projects.length === 0 && !showCreate ? (
        <div className="rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 p-16 text-center text-neutral-400">
          No projects yet. Click &ldquo;New Project&rdquo; to create one.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <div key={p.project_id} className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5 shadow-sm hover:shadow-md transition-shadow">
              {editId === p.project_id ? (
                <div className="space-y-2">
                  <input
                    autoFocus
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                    onKeyDown={(e) => e.key === "Enter" && void handleUpdate(p.project_id)}
                    className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                  />
                  <input
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 px-2 py-1.5 text-xs text-neutral-500 focus:border-blue-500 focus:outline-none"
                    placeholder="Description (optional)"
                  />
                  <div className="flex gap-2">
                    <button onClick={() => void handleUpdate(p.project_id)} className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700">Save</button>
                    <button onClick={() => setEditId(null)} className="rounded-lg border border-neutral-300 px-3 py-1 text-xs text-neutral-600 hover:bg-neutral-50">Cancel</button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 dark:bg-blue-950">
                        <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" /></svg>
                      </div>
                      <div>
                        <h3 className="font-semibold text-neutral-900 dark:text-neutral-100">{p.name}</h3>
                        <p className="text-xs text-neutral-500 dark:text-neutral-400">{new Date(p.created_at).toLocaleDateString()}</p>
                      </div>
                    </div>
                    <span className="rounded-full bg-green-100 dark:bg-green-950 px-2 py-0.5 text-xs font-medium text-green-700 dark:text-green-400">Active</span>
                  </div>
                  {p.description && (
                    <p className="mt-3 text-sm text-neutral-500 dark:text-neutral-400 line-clamp-2">{p.description}</p>
                  )}
                  <div className="mt-3 flex items-center gap-3 text-xs text-neutral-500 dark:text-neutral-400">
                    <span className="flex items-center gap-1">
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>
                      {procedureCounts[p.project_id] ?? 0} procedure{(procedureCounts[p.project_id] ?? 0) !== 1 ? "s" : ""}
                    </span>
                  </div>
                  <div className="mt-4 flex gap-2">
                    <Link
                      href={`/procedures?project_id=${p.project_id}`}
                      className="flex-1 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/50 px-3 py-1.5 text-center text-xs font-medium text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-950 transition-colors"
                    >
                      Procedures
                    </Link>
                    <button
                      onClick={() => startEdit(p)}
                      className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => void handleDelete(p)}
                      className="rounded-lg border border-red-200 dark:border-red-900 px-3 py-1.5 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950"
                    >
                      Delete
                    </button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete !== null}
        title="Delete Project"
        message={confirmDelete ? `Delete "${confirmDelete.name}"? Procedures linked to it will lose their project association.` : ""}
        confirmLabel="Delete"
        danger
        onConfirm={doDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
