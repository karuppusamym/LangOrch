"use client";

import { useEffect, useState } from "react";
import { listProjects, createProject, updateProject, deleteProject } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { Project } from "@/lib/types";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
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
      setProjects(await listProjects());
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Projects</h1>
          <p className="text-sm text-gray-500">{projects.length} project(s)</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
        >
          + New Project
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold">Create Project</h3>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs text-gray-500">Name *</label>
              <input
                autoFocus
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                onKeyDown={(e) => e.key === "Enter" && void handleCreate()}
                className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                placeholder="My Project"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">Description</label>
              <textarea
                rows={2}
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                placeholder="Optional description"
              />
            </div>
          </div>
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
          <div className="mt-4 flex gap-2">
            <button
              onClick={() => void handleCreate()}
              className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
            >
              Create
            </button>
            <button
              onClick={() => { setShowCreate(false); setError(""); setForm({ name: "", description: "" }); }}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* List */}
      {loading ? (
        <p className="text-gray-500">Loading projects…</p>
      ) : projects.length === 0 && !showCreate ? (
        <div className="rounded-xl border border-dashed border-gray-300 p-12 text-center text-gray-400">
          No projects yet. Click &ldquo;+ New Project&rdquo; to create one.
        </div>
      ) : (
        <div className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white shadow-sm">
          {projects.map((p) => (
            <div key={p.project_id} className="flex items-center gap-4 p-4">
              {editId === p.project_id ? (
                /* Inline edit */
                <div className="flex flex-1 flex-col gap-2">
                  <input
                    autoFocus
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                    onKeyDown={(e) => e.key === "Enter" && void handleUpdate(p.project_id)}
                    className="w-full rounded-lg border border-gray-300 p-1.5 text-sm focus:border-primary-500 focus:outline-none"
                  />
                  <input
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    className="w-full rounded-lg border border-gray-300 p-1.5 text-xs text-gray-500 focus:border-primary-500 focus:outline-none"
                    placeholder="Description (optional)"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => void handleUpdate(p.project_id)}
                      className="rounded-lg bg-primary-600 px-3 py-1 text-xs font-medium text-white hover:bg-primary-700"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => setEditId(null)}
                      className="rounded-lg border border-gray-300 px-3 py-1 text-xs text-gray-600 hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                /* Normal row */
                <>
                  <div className="flex-1">
                    <p className="font-medium text-gray-900">{p.name}</p>
                    {p.description && (
                      <p className="text-xs text-gray-500">{p.description}</p>
                    )}
                    <p className="mt-0.5 text-xs text-gray-400">
                      Created {new Date(p.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => startEdit(p)}
                      className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => void handleDelete(p)}
                      className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
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
