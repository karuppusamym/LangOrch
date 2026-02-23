"use client";

import { useEffect, useState } from "react";
import { listSecrets, createSecret, updateSecret, deleteSecret } from "@/lib/api";
import type { Secret } from "@/lib/types";

const PROVIDER_META: Record<string, { label: string; color: string }> = {
  db:    { label: "Database",  color: "bg-blue-100 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400" },
  vault: { label: "HashiCorp Vault", color: "bg-purple-100 dark:bg-purple-950/40 text-purple-700 dark:text-purple-400" },
  aws:   { label: "AWS SM",    color: "bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400" },
  azure: { label: "Azure KV",  color: "bg-sky-100 dark:bg-sky-950/40 text-sky-700 dark:text-sky-400" },
  env:   { label: "Env Var",   color: "bg-emerald-100 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400" },
};

type Modal =
  | { type: "create" }
  | { type: "edit"; secret: Secret }
  | { type: "delete"; secret: Secret }
  | null;

export default function SecretsPage() {
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal]     = useState<Modal>(null);
  const [search, setSearch]   = useState("");
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState("");

  const [fName, setFName]           = useState("");
  const [fValue, setFValue]         = useState("");
  const [fDescription, setFDesc]    = useState("");
  const [fProvider, setFProvider]   = useState("db");
  const [fTags, setFTags]           = useState("");

  async function reload() {
    try {
      setLoading(true);
      setSecrets(await listSecrets());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load secrets");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void reload(); }, []);

  function openCreate() {
    setFName(""); setFValue(""); setFDesc(""); setFProvider("db"); setFTags("");
    setError(""); setModal({ type: "create" });
  }

  function openEdit(s: Secret) {
    setFName(s.name); setFValue(""); setFDesc(s.description ?? "");
    setFProvider(s.provider_hint ?? "db"); setFTags((s.tags ?? []).join(", "));
    setError(""); setModal({ type: "edit", secret: s });
  }

  function parseTags(raw: string): string[] {
    return raw.split(",").map((t) => t.trim()).filter(Boolean);
  }

  async function handleSave() {
    setSaving(true); setError("");
    try {
      if (modal?.type === "create") {
        await createSecret({
          name: fName, value: fValue, description: fDescription || undefined,
          provider_hint: fProvider, tags: parseTags(fTags),
        });
      } else if (modal?.type === "edit") {
        await updateSecret((modal as { type: "edit"; secret: Secret }).secret.name, {
          value: fValue || undefined, description: fDescription || undefined,
          provider_hint: fProvider, tags: parseTags(fTags),
        });
      }
      await reload(); setModal(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (modal?.type !== "delete") return;
    setSaving(true); setError("");
    try {
      await deleteSecret((modal as { type: "delete"; secret: Secret }).secret.name);
      await reload(); setModal(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setSaving(false);
    }
  }

  const filtered = secrets.filter(
    (s) => !search || s.name.toLowerCase().includes(search.toLowerCase()) ||
      (s.description ?? "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">Secrets</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">Manage encrypted secrets and external vault references</p>
        </div>
        <button onClick={openCreate} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors flex items-center gap-2">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" /></svg>
          Add Secret
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {Object.entries(PROVIDER_META).map(([key, meta]) => (
          <div key={key} className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3 flex flex-col gap-1">
            <span className={"self-start rounded-full px-2 py-0.5 text-xs font-medium " + meta.color}>{meta.label}</span>
            <p className="text-xl font-bold text-neutral-900 dark:text-neutral-100">
              {secrets.filter((s) => (s.provider_hint ?? "db") === key).length}
            </p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search secrets..."
            className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 pl-9 pr-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" /></div>
      ) : (
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-800/50 border-b border-neutral-200 dark:border-neutral-700">
              <tr className="text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                <th className="px-5 py-3">Name</th>
                <th className="px-5 py-3">Provider</th>
                <th className="px-5 py-3">Description</th>
                <th className="px-5 py-3">Tags</th>
                <th className="px-5 py-3">Created By</th>
                <th className="px-5 py-3">Updated</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {filtered.length === 0 ? (
                <tr><td colSpan={7} className="px-5 py-12 text-center text-neutral-400">No secrets found.</td></tr>
              ) : filtered.map((s) => {
                const p = PROVIDER_META[s.provider_hint ?? "db"] ?? PROVIDER_META.db;
                return (
                  <tr key={s.secret_id} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/40 transition-colors">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2">
                        <svg className="w-4 h-4 text-neutral-400 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                        </svg>
                        <span className="font-mono font-medium text-neutral-900 dark:text-neutral-100">{s.name}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <span className={"rounded-full px-2 py-0.5 text-xs font-medium " + p.color}>{p.label}</span>
                    </td>
                    <td className="px-5 py-3 text-neutral-500 dark:text-neutral-400 max-w-xs truncate">{s.description ?? ""}</td>
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap gap-1">
                        {(s.tags ?? []).length === 0 ? <span className="text-neutral-300 dark:text-neutral-600"></span> :
                          (s.tags ?? []).map((t) => <span key={t} className="rounded px-1.5 py-0.5 text-xs bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400">{t}</span>)}
                      </div>
                    </td>
                    <td className="px-5 py-3 text-xs text-neutral-400">{s.created_by ?? ""}</td>
                    <td className="px-5 py-3 text-xs text-neutral-400">{new Date(s.updated_at).toLocaleDateString()}</td>
                    <td className="px-5 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button onClick={() => openEdit(s)} className="rounded-md px-2.5 py-1 text-xs font-medium bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors">Edit</button>
                        <button onClick={() => { setModal({ type: "delete", secret: s }); setError(""); }} className="rounded-md px-2.5 py-1 text-xs font-medium bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-950/50 transition-colors">Delete</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {(modal?.type === "create" || modal?.type === "edit") && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-xl p-6 space-y-5 max-h-screen overflow-y-auto">
            <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
              {modal.type === "create" ? "Add Secret" : "Edit Secret"}
            </h2>
            {error && <div className="rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 px-3 py-2 text-sm text-red-600 dark:text-red-400">{error}</div>}
            {modal.type === "create" && (
              <div>
                <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Name * <span className="text-neutral-400 font-normal">(unique key)</span></label>
                <input value={fName} onChange={(e) => setFName(e.target.value)} placeholder="my-api-key"
                  className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none" />
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                {modal.type === "create" ? "Value *" : "New Value (blank = unchanged)"}
              </label>
              <input type="password" value={fValue} onChange={(e) => setFValue(e.target.value)} placeholder=""
                className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
              <p className="text-xs text-neutral-400 mt-1">Values are encrypted at rest with AES-Fernet. Never stored in plaintext.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Provider</label>
              <select value={fProvider} onChange={(e) => setFProvider(e.target.value)}
                className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none">
                {Object.entries(PROVIDER_META).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Description</label>
              <textarea value={fDescription} onChange={(e) => setFDesc(e.target.value)} rows={2} placeholder="Optional description..."
                className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm resize-none focus:border-blue-500 focus:outline-none" />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Tags <span className="text-neutral-400 font-normal">(comma-separated)</span></label>
              <input value={fTags} onChange={(e) => setFTags(e.target.value)} placeholder="prod, payments, external"
                className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
            </div>
            <div className="flex justify-end gap-3">
              <button onClick={() => setModal(null)} className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-4 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">Cancel</button>
              <button onClick={handleSave} disabled={saving} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">
                {saving ? "Saving..." : modal.type === "create" ? "Add Secret" : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {modal?.type === "delete" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-xl p-6 space-y-5">
            <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Delete Secret</h2>
            {error && <div className="rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 px-3 py-2 text-sm text-red-600 dark:text-red-400">{error}</div>}
            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              Permanently delete secret <strong className="font-mono">{(modal as { type: "delete"; secret: Secret }).secret.name}</strong>? This cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setModal(null)} className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-4 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">Cancel</button>
              <button onClick={handleDelete} disabled={saving} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors">
                {saving ? "Deleting..." : "Delete Secret"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
