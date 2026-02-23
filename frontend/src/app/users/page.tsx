"use client";

import { useEffect, useState } from "react";
import { listUsers, createUser, updateUser, deleteUser } from "@/lib/api";
import type { User } from "@/lib/types";
import { ROLE_LABELS, ROLE_COLORS, ROLES } from "@/lib/auth";

type Modal = { type: "create" } | { type: "edit"; user: User } | { type: "delete"; user: User } | null;

export default function UsersPage() {
  const [users, setUsers]   = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal]   = useState<Modal>(null);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState("");

  const [fUsername, setFUsername] = useState("");
  const [fEmail, setFEmail]       = useState("");
  const [fFullName, setFFullName] = useState("");
  const [fRole, setFRole]         = useState("viewer");
  const [fPassword, setFPassword] = useState("");
  const [fActive, setFActive]     = useState(true);

  async function reload() {
    try {
      setLoading(true);
      setUsers(await listUsers());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void reload(); }, []);

  function openCreate() {
    setFUsername(""); setFEmail(""); setFFullName(""); setFRole("viewer"); setFPassword(""); setFActive(true);
    setModal({ type: "create" });
    setError("");
  }

  function openEdit(user: User) {
    setFUsername(user.username); setFEmail(user.email); setFFullName(user.full_name ?? "");
    setFRole(user.role); setFPassword(""); setFActive(user.is_active);
    setModal({ type: "edit", user });
    setError("");
  }

  async function handleSave() {
    setSaving(true); setError("");
    try {
      if (modal?.type === "create") {
        await createUser({ username: fUsername, email: fEmail, password: fPassword, full_name: fFullName || undefined, role: fRole });
      } else if (modal?.type === "edit") {
        await updateUser((modal as { type: "edit"; user: User }).user.user_id, {
          email: fEmail, full_name: fFullName || undefined, role: fRole, is_active: fActive,
          password: fPassword || undefined,
        });
      }
      await reload();
      setModal(null);
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
      await deleteUser((modal as { type: "delete"; user: User }).user.user_id);
      await reload();
      setModal(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setSaving(false);
    }
  }

  const filtered = users.filter((u) =>
    !search || u.username.toLowerCase().includes(search.toLowerCase()) ||
    u.email.toLowerCase().includes(search.toLowerCase()) ||
    (u.full_name ?? "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">Users</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">Manage platform users and their roles</p>
        </div>
        <button onClick={openCreate} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors flex items-center gap-2">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" /></svg>
          Add User
        </button>
      </div>

      <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4 shadow-sm">
        <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400 mb-3 uppercase tracking-wide">Role Hierarchy (ascending privilege)</p>
        <div className="flex flex-wrap gap-2 items-center">
          {[...ROLES].map((r, i) => (
            <div key={r} className="flex items-center gap-2">
              {i > 0 && <span className="text-neutral-300 dark:text-neutral-600 text-sm">&lt;</span>}
              <span className={"rounded-full px-2.5 py-0.5 text-xs font-medium " + (ROLE_COLORS[r] ?? "")}>{ROLE_LABELS[r]}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search users..."
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
                <th className="px-5 py-3">User</th>
                <th className="px-5 py-3">Role</th>
                <th className="px-5 py-3">Auth Provider</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3">Joined</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {filtered.length === 0 ? (
                <tr><td colSpan={6} className="px-5 py-12 text-center text-neutral-400">No users found.</td></tr>
              ) : filtered.map((u) => {
                const initials = (u.full_name ?? u.username).slice(0, 2).toUpperCase();
                return (
                  <tr key={u.user_id} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/40 transition-colors">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <div className="h-8 w-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold shrink-0">{initials}</div>
                        <div>
                          <p className="font-medium text-neutral-900 dark:text-neutral-100">{u.full_name ?? u.username}</p>
                          <p className="text-xs text-neutral-400">{u.email}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <span className={"rounded-full px-2.5 py-1 text-xs font-medium " + (ROLE_COLORS[u.role] ?? ROLE_COLORS.viewer)}>
                        {ROLE_LABELS[u.role] ?? u.role}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-xs text-neutral-500 dark:text-neutral-400 capitalize">{u.sso_provider ?? "local"}</td>
                    <td className="px-5 py-3">
                      <span className={"inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium " + (u.is_active ? "bg-emerald-100 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400" : "bg-neutral-100 dark:bg-neutral-800 text-neutral-500")}>
                        <span className={"h-1.5 w-1.5 rounded-full " + (u.is_active ? "bg-emerald-500" : "bg-neutral-400")} />
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-xs text-neutral-400">{new Date(u.created_at).toLocaleDateString()}</td>
                    <td className="px-5 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button onClick={() => openEdit(u)} className="rounded-md px-2.5 py-1 text-xs font-medium bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors">Edit</button>
                        <button onClick={() => { setModal({ type: "delete", user: u }); setError(""); }} className="rounded-md px-2.5 py-1 text-xs font-medium bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-950/50 transition-colors">Delete</button>
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
          <div className="w-full max-w-md rounded-2xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-xl p-6 space-y-5">
            <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
              {modal.type === "create" ? "Add User" : "Edit User"}
            </h2>
            {error && <div className="rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 px-3 py-2 text-sm text-red-600 dark:text-red-400">{error}</div>}
            <div className="space-y-4">
              {modal.type === "create" && (
                <div>
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Username *</label>
                  <input value={fUsername} onChange={(e) => setFUsername(e.target.value)} placeholder="john.doe"
                    className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
                </div>
              )}
              <div>
                <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Full Name</label>
                <input value={fFullName} onChange={(e) => setFFullName(e.target.value)} placeholder="John Doe"
                  className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Email *</label>
                <input type="email" value={fEmail} onChange={(e) => setFEmail(e.target.value)} placeholder="john@example.com"
                  className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  {modal.type === "create" ? "Password *" : "New Password (blank = unchanged)"}
                </label>
                <input type="password" value={fPassword} onChange={(e) => setFPassword(e.target.value)} placeholder="..."
                  className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Role</label>
                <select value={fRole} onChange={(e) => setFRole(e.target.value)}
                  className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none">
                  {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]} ({r})</option>)}
                </select>
              </div>
              {modal.type === "edit" && (
                <div className="flex items-center gap-3">
                  <button onClick={() => setFActive((v) => !v)} role="switch" aria-checked={fActive}
                    className={"relative inline-flex h-6 w-11 rounded-full transition-colors " + (fActive ? "bg-blue-600" : "bg-neutral-300 dark:bg-neutral-600")}>
                    <span className={"inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform mt-0.5 " + (fActive ? "translate-x-5" : "translate-x-0.5")} />
                  </button>
                  <span className="text-sm text-neutral-700 dark:text-neutral-300">Account active</span>
                </div>
              )}
            </div>
            <div className="flex justify-end gap-3">
              <button onClick={() => setModal(null)} className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-4 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">Cancel</button>
              <button onClick={handleSave} disabled={saving}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">
                {saving ? "Saving..." : modal.type === "create" ? "Create User" : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {modal?.type === "delete" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-xl p-6 space-y-5">
            <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Delete User</h2>
            {error && <div className="rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 px-3 py-2 text-sm text-red-600 dark:text-red-400">{error}</div>}
            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              Are you sure you want to delete <strong>{(modal as { type: "delete"; user: User }).user.username}</strong>? This action cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setModal(null)} className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-4 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">Cancel</button>
              <button onClick={handleDelete} disabled={saving} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors">
                {saving ? "Deleting..." : "Delete User"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
