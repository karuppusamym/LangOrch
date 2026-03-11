"use client";

import { useCallback, useEffect, useState } from "react";
import { listAuditEvents, type AuditEventRecord } from "@/lib/api";

const CATEGORY_META: Record<string, { label: string; color: string; bg: string; icon: string }> = {
  user_mgmt: { label: "User Mgmt", color: "text-blue-700", bg: "bg-blue-50", icon: "👤" },
  secret_mgmt: { label: "Secrets", color: "text-yellow-700", bg: "bg-yellow-50", icon: "🔑" },
  auth: { label: "Auth", color: "text-green-700", bg: "bg-green-50", icon: "🔒" },
  config: { label: "Config", color: "text-purple-700", bg: "bg-purple-50", icon: "⚙️" },
  run: { label: "Run", color: "text-neutral-700", bg: "bg-neutral-100", icon: "▶" },
};

const ACTION_COLORS: Record<string, string> = {
  create: "bg-emerald-100 text-emerald-800",
  update: "bg-blue-100 text-blue-800",
  delete: "bg-red-100 text-red-800",
  login: "bg-green-100 text-green-800",
  login_failed: "bg-red-100 text-red-800",
  patch: "bg-orange-100 text-orange-800",
};

function formatTs(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEventRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [action, setAction] = useState("");

  // Expanded row
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [auditPage, setAuditPage] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAuditEvents({
        search: search || undefined,
        category: category || undefined,
        action: action || undefined,
        limit: 200,
      });
      setEvents(res.events);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load audit events");
    } finally {
      setLoading(false);
    }
  }, [search, category, action]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => { setAuditPage(0); }, [search, category, action]);

  const categories = Object.keys(CATEGORY_META);
  const actions = ["create", "update", "delete", "login", "login_failed", "patch"];
  const AUDIT_PAGE_SIZE = 25;
  const totalAuditPages = Math.ceil(events.length / AUDIT_PAGE_SIZE);
  const pagedEvents = events.slice(auditPage * AUDIT_PAGE_SIZE, (auditPage + 1) * AUDIT_PAGE_SIZE);

  return (
    <div className="min-h-[calc(100vh-4rem)] space-y-6 bg-neutral-50 p-6">
      {/* Header */}
      <section className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-neutral-400">Security Observability</p>
            <h1 className="mt-1 text-2xl font-semibold text-neutral-900 dark:text-neutral-100">Audit Log</h1>
            <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">System-level events for user, secret, auth, and config changes.</p>
          </div>
          <div className="flex items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
            <span className="rounded-full border border-neutral-200 bg-neutral-50 px-2.5 py-1 dark:border-neutral-700 dark:bg-neutral-800">{events.length} loaded</span>
            <button
              onClick={load}
              className="rounded-full border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-100 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"
            >
              Refresh
            </button>
          </div>
        </div>
      </section>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-neutral-200 bg-white p-3 shadow-sm">
        <input
          type="search"
          placeholder="Search description…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="min-w-[180px] flex-1 rounded-2xl border border-neutral-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-200"
        />
        <select
          aria-label="Filter by category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-2xl border border-neutral-300 px-3 py-2 text-sm focus:outline-none focus:border-sky-500"
        >
          <option value="">All Categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>{CATEGORY_META[c].label}</option>
          ))}
        </select>
        <select
          aria-label="Filter by action"
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="rounded-2xl border border-neutral-300 px-3 py-2 text-sm focus:outline-none focus:border-sky-500"
        >
          <option value="">All Actions</option>
          {actions.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        {(search || category || action) && (
          <button
            onClick={() => { setSearch(""); setCategory(""); setAction(""); }}
            className="text-sm text-neutral-400 hover:text-neutral-600"
          >
            ✕ Clear
          </button>
        )}
        <span className="ml-auto text-xs text-neutral-400">
          {loading ? "Loading…" : `${events.length} event${events.length !== 1 ? "s" : ""}`}
        </span>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-100 bg-neutral-50">
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Time</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Category</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Action</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Actor</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Description</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Resource</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={6} className="py-12 text-center text-sm text-neutral-400">Loading…</td>
              </tr>
            )}
            {!loading && events.length === 0 && (
              <tr>
                <td colSpan={6} className="py-12 text-center text-sm text-neutral-400">
                  No audit events found.
                  {(search || category || action) && " Try clearing the filters."}
                </td>
              </tr>
            )}
            {pagedEvents.map((ev) => {
              const meta = CATEGORY_META[ev.category];
              const isExpanded = expandedId === ev.event_id;
              return (
                <>
                  <tr
                    key={ev.event_id}
                    onClick={() => setExpandedId(isExpanded ? null : ev.event_id)}
                    className="cursor-pointer border-b border-neutral-100 hover:bg-neutral-50 transition-colors"
                  >
                    <td className="whitespace-nowrap px-4 py-2.5 text-xs font-mono text-neutral-500">
                      {formatTs(ev.ts)}
                    </td>
                    <td className="px-4 py-2.5">
                      {meta ? (
                        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${meta.bg} ${meta.color}`}>
                          {meta.icon} {meta.label}
                        </span>
                      ) : (
                        <span className="text-xs text-neutral-500">{ev.category}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${ACTION_COLORS[ev.action] ?? "bg-neutral-100 text-neutral-700"}`}>
                        {ev.action}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs font-medium text-neutral-700">{ev.actor}</td>
                    <td className="max-w-xs truncate px-4 py-2.5 text-xs text-neutral-600">{ev.description}</td>
                    <td className="px-4 py-2.5 text-xs text-neutral-400">
                      {ev.resource_type && (
                        <span className="font-mono">{ev.resource_type}{ev.resource_id ? `:${ev.resource_id}` : ""}</span>
                      )}
                    </td>
                  </tr>
                  {isExpanded && ev.meta && (
                    <tr key={`${ev.event_id}-meta`} className="border-b border-neutral-100 bg-neutral-50">
                      <td colSpan={6} className="px-8 py-3">
                        <pre className="max-h-40 overflow-auto rounded-2xl border border-neutral-200 bg-white p-2 font-mono whitespace-pre-wrap text-[11px] text-neutral-600">
                          {JSON.stringify(ev.meta, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
      {totalAuditPages > 1 && (
        <div className="flex items-center justify-between px-2 py-1">
          <span className="text-xs text-neutral-400">{auditPage * AUDIT_PAGE_SIZE + 1}–{Math.min((auditPage + 1) * AUDIT_PAGE_SIZE, events.length)} of {events.length} events</span>
          <div className="flex items-center gap-1.5">
            <button onClick={() => setAuditPage((p) => Math.max(0, p - 1))} disabled={auditPage === 0}
              className="rounded-full border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-40">
              ← Prev
            </button>
            <span className="px-2 text-xs text-neutral-500">{auditPage + 1} / {totalAuditPages}</span>
            <button onClick={() => setAuditPage((p) => Math.min(totalAuditPages - 1, p + 1))} disabled={auditPage >= totalAuditPages - 1}
              className="rounded-full border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-40">
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
