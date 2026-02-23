"use client";

import { useEffect, useState } from "react";
import { listRuns, listApprovals } from "@/lib/api";
import type { Run, Approval } from "@/lib/types";

type AuditEvent = {
  id: string;
  timestamp: string;
  type: "execution" | "approval" | "access" | "system";
  action: string;
  user: string;
  details: string;
};

function buildAuditEvents(runs: Run[], approvals: Approval[]): AuditEvent[] {
  const events: AuditEvent[] = [];

  for (const run of runs) {
    events.push({
      id: `run-start-${run.run_id}`,
      timestamp: run.created_at,
      type: "execution",
      action: `Workflow run created: ${run.procedure_id} v${run.procedure_version}`,
      user: "system",
      details: `Run ID: ${run.run_id} | Status: ${run.status}`,
    });
    if (run.ended_at && run.status !== "created") {
      events.push({
        id: `run-end-${run.run_id}`,
        timestamp: run.ended_at,
        type: "execution",
        action: `Workflow run ${run.status}: ${run.procedure_id}`,
        user: "system",
        details: `Run ID: ${run.run_id}`,
      });
    }
  }

  for (const a of approvals) {
    events.push({
      id: `approval-${a.approval_id}`,
      timestamp: a.decided_at ?? a.created_at,
      type: "approval",
      action: a.decided_at
        ? `Approval ${a.status} by ${a.decided_by ?? "unknown"}`
        : "Approval requested",
      user: a.decided_by ?? "system",
      details: `Node: ${a.node_id} | Run: ${a.run_id.slice(0, 8)}…`,
    });
  }

  return events.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
}

const TYPE_STYLES: Record<string, string> = {
  execution: "bg-blue-100 dark:bg-blue-950/50 text-blue-700 dark:text-blue-400",
  approval:  "bg-amber-100 dark:bg-amber-950/50 text-amber-700 dark:text-amber-400",
  access:    "bg-purple-100 dark:bg-purple-950/50 text-purple-700 dark:text-purple-400",
  system:    "bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-400",
};

export default function AuditLogsPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const [runs, approvals] = await Promise.all([
          listRuns({ limit: 100, order: "desc" }),
          listApprovals(),
        ]);
        setEvents(buildAuditEvents(runs, approvals));
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  const filtered = events.filter((e) => {
    const matchSearch = !search || e.action.toLowerCase().includes(search.toLowerCase()) || e.details.toLowerCase().includes(search.toLowerCase()) || e.user.toLowerCase().includes(search.toLowerCase());
    const matchType = !typeFilter || e.type === typeFilter;
    return matchSearch && matchType;
  });

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">Audit Logs</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">Track all system activities and workflow events</p>
        </div>
        <span className="text-xs text-neutral-400">{filtered.length} events</span>
      </div>

      {/* Filters */}
      <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search events…"
              className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 pl-9 pr-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
          </div>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}
            className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 focus:border-blue-500 focus:outline-none">
            <option value="">All Types</option>
            <option value="execution">Execution</option>
            <option value="approval">Approval</option>
            <option value="access">Access</option>
            <option value="system">System</option>
          </select>
        </div>
      </div>

      {/* Audit table */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 p-16 text-center text-neutral-400">
          No audit events found.
        </div>
      ) : (
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-800/50 border-b border-neutral-200 dark:border-neutral-700">
              <tr className="text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                <th className="px-4 py-3">Timestamp</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {filtered.map((event) => (
                <tr key={event.id} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/50 transition-colors">
                  <td className="px-4 py-3 text-xs font-mono text-neutral-500 dark:text-neutral-400 whitespace-nowrap">
                    {new Date(event.timestamp).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${TYPE_STYLES[event.type] ?? TYPE_STYLES.system}`}>
                      {event.type}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-neutral-800 dark:text-neutral-200">{event.action}</td>
                  <td className="px-4 py-3 text-xs text-neutral-500 dark:text-neutral-400">{event.user}</td>
                  <td className="px-4 py-3 text-xs text-neutral-400 max-w-[280px] truncate" title={event.details}>
                    {event.details}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
