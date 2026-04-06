"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { cleanupRuns, deleteRun, listRuns, cancelRun, retryRun } from "@/lib/api";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { useToast } from "@/components/Toast";
import type { Run } from "@/lib/types";

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");
  const [order, setOrder] = useState<"desc" | "asc">("desc");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [cleanupBefore, setCleanupBefore] = useState("");
  const [cleanupPreviewCount, setCleanupPreviewCount] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState<"cancel" | "delete" | null>(null);
  const [search, setSearch] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const PAGE_SIZE = 100;
  const { toast } = useToast();

  // Auto-refresh every 15s when active runs exist
  useEffect(() => {
    const hasActive = runs.some((r) => r.status === "running" || r.status === "created" || r.status === "waiting_approval");
    if (hasActive && !pollRef.current) {
      pollRef.current = setInterval(() => void loadRuns(0), 15_000);
    } else if (!hasActive && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [runs]);

  useEffect(() => {
    setOffset(0);
    void loadRuns(0);
  }, [order, createdFrom, createdTo]);

  async function loadRuns(newOffset = 0, append = false) {
    try {
      const data = await listRuns({
        order,
        createdFrom: createdFrom ? new Date(createdFrom).toISOString() : undefined,
        createdTo: createdTo ? new Date(createdTo).toISOString() : undefined,
        limit: PAGE_SIZE,
        offset: newOffset,
      });
      if (append) {
        setRuns((prev) => [...prev, ...data]);
      } else {
        setRuns(data);
      }
      setHasMore(data.length === PAGE_SIZE);
    } catch (err) {
      console.error(err);
      toast(err instanceof Error ? err.message : "Failed to load runs", "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleCancel(runId: string) {
    try {
      await cancelRun(runId);
      loadRuns();
    } catch (err) {
      console.error(err);
    }
  }

  async function handleRetry(runId: string) {
    try {
      await retryRun(runId);
      toast("Retry queued", "success");
      void loadRuns(0);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to retry", "error");
    }
  }

  async function handleDelete(runId: string) {
    setConfirmDeleteId(runId);
  }

  async function confirmDelete() {
    if (!confirmDeleteId) return;
    const runId = confirmDeleteId;
    setConfirmDeleteId(null);
    try {
      await deleteRun(runId);
      loadRuns();
    } catch (err) {
      console.error(err);
    }
  }

  function toggleSelect(runId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  }

  function toggleSelectAll() {
    if (selectedIds.size === filteredRuns.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredRuns.map((r) => r.run_id)));
    }
  }

  async function executeBulkAction() {
    if (!bulkAction || selectedIds.size === 0) return;
    const action = bulkAction;
    setBulkAction(null);
    const ids = Array.from(selectedIds);
    let successCount = 0;
    for (const id of ids) {
      try {
        if (action === "cancel") await cancelRun(id);
        else if (action === "delete") await deleteRun(id);
        successCount++;
      } catch { /* skip individual failures */ }
    }
    setSelectedIds(new Set());
    loadRuns();
    console.log(`Bulk ${action}: ${successCount}/${ids.length} succeeded`);
  }

  async function handleCleanup() {
    if (!cleanupBefore) return;
    try {
      await cleanupRuns(new Date(cleanupBefore).toISOString(), filter === "all" ? undefined : filter);
      setCleanupPreviewCount(null);
      loadRuns();
    } catch (err) {
      console.error(err);
    }
  }

  async function handlePreviewCleanup() {
    if (!cleanupBefore) {
      setCleanupPreviewCount(null);
      return;
    }
    try {
      const preview = await listRuns({
        status: filter === "all" ? undefined : filter,
        createdTo: new Date(cleanupBefore).toISOString(),
        order: "desc",
      });
      setCleanupPreviewCount(preview.length);
    } catch (err) {
      console.error(err);
      setCleanupPreviewCount(null);
    }
  }

  function applyPreset(days: number) {
    const now = new Date();
    const from = new Date(now);
    from.setDate(now.getDate() - days);
    setCreatedFrom(from.toISOString().slice(0, 10));
    setCreatedTo(now.toISOString().slice(0, 10));
  }

  const filteredRuns = runs.filter((r) => {
    if (filter !== "all" && r.status !== filter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      r.run_id.toLowerCase().includes(q) ||
      r.procedure_id.toLowerCase().includes(q) ||
      r.status.toLowerCase().includes(q) ||
      (r.thread_id ?? "").toLowerCase().includes(q)
    );
  });

  const statusCounts = runs.reduce(
    (acc, r) => { acc[r.status] = (acc[r.status] || 0) + 1; return acc; },
    {} as Record<string, number>
  );

  return (
    <div className="min-h-[calc(100vh-4rem)] space-y-5 bg-neutral-50 p-6">
      <div className="space-y-4">
        <section className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="mt-1 flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Runs</h1>
              </div>
              <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">Monitor and manage procedure executions</p>
            </div>
            <button
              onClick={() => { setOffset(0); void loadRuns(0); }}
              className="inline-flex items-center gap-2 rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 transition hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
              Refresh
            </button>
          </div>

          <div className="mt-4 grid items-start gap-2.5 md:grid-cols-3">
            {[
              { label: "Total", value: runs.length, meta: "loaded", tone: "text-neutral-900 dark:text-neutral-100" },
              { label: "Running", value: statusCounts.running ?? 0, meta: "active now", tone: "text-blue-600" },
              { label: "Failed", value: statusCounts.failed ?? 0, meta: "needs review", tone: "text-red-600" },
            ].map((card) => (
              <div key={card.label} className="self-start rounded-2xl border border-neutral-200 bg-white px-4 py-3 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-400">{card.label}</p>
                <div className="mt-2 flex items-end justify-between gap-3">
                  <p className={`text-2xl font-semibold ${card.tone}`}>{card.value}</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{card.meta}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-2 rounded-2xl border border-neutral-200 bg-white px-4 py-3 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="relative min-w-[220px] flex-1">
                  <svg className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
                  <input
                    type="search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search run ID, procedure, status..."
                    className="w-full rounded-2xl border border-neutral-300 bg-neutral-50 py-2 pl-9 pr-3 text-sm text-neutral-900 outline-none transition focus:border-sky-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100"
                  />
              </div>
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                aria-label="Filter runs by status"
                className="rounded-2xl border border-neutral-300 bg-white px-3.5 py-2 text-sm text-neutral-700 outline-none transition focus:border-sky-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-300"
              >
                <option value="all">All status</option>
                <option value="created">Created</option>
                <option value="running">Running</option>
                <option value="waiting_approval">Waiting Approval</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="canceled">Canceled</option>
              </select>
              <select
                value={order}
                onChange={(e) => setOrder(e.target.value as "asc" | "desc")}
                aria-label="Sort runs by created date"
                className="rounded-2xl border border-neutral-300 bg-white px-3.5 py-2 text-sm text-neutral-700 outline-none transition focus:border-sky-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-300"
              >
                <option value="desc">Newest first</option>
                <option value="asc">Oldest first</option>
              </select>
              <input type="date" value={createdFrom} onChange={(e) => setCreatedFrom(e.target.value)} title="From date"
                className="rounded-2xl border border-neutral-300 bg-white px-3.5 py-2 text-sm text-neutral-700 outline-none transition focus:border-sky-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-300" />
              <input type="date" value={createdTo} onChange={(e) => setCreatedTo(e.target.value)} title="To date"
                className="rounded-2xl border border-neutral-300 bg-white px-3.5 py-2 text-sm text-neutral-700 outline-none transition focus:border-sky-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-300" />
              <div className="flex items-center gap-1.5">
                {[1, 7, 30].map((d) => (
                  <button key={d} onClick={() => applyPreset(d)}
                    className="rounded-full border border-neutral-300 px-2.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800">
                    {d === 1 ? "24h" : `${d}d`}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        <details className="rounded-2xl border border-neutral-200 bg-white px-4 py-3 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
          <summary className="cursor-pointer list-none text-sm font-medium text-neutral-700 dark:text-neutral-200">
            Cleanup Tools
          </summary>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-neutral-500 dark:text-neutral-400">Cleanup before:</span>
            <input type="date" value={cleanupBefore} onChange={(e) => setCleanupBefore(e.target.value)} title="Cleanup before"
              className="rounded-full border border-neutral-300 bg-white px-3 py-1.5 text-xs text-neutral-700 outline-none transition focus:border-sky-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-300" />
            <button onClick={handlePreviewCleanup} disabled={!cleanupBefore}
              className="rounded-full border border-neutral-300 px-3 py-1.5 text-xs text-neutral-600 hover:bg-neutral-100 disabled:opacity-40 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800">
              Preview
            </button>
            <button onClick={handleCleanup} disabled={!cleanupBefore}
              className="rounded-full border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-40 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950/40">
              Cleanup
            </button>
            {cleanupPreviewCount !== null && (
              <span className="text-neutral-400 dark:text-neutral-500">~{cleanupPreviewCount} run(s) will be deleted</span>
            )}
          </div>
        </details>

        {selectedIds.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-[20px] border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm text-blue-700 shadow-sm dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-300">
            <span className="font-medium">{selectedIds.size} selected</span>
            <button onClick={() => setBulkAction("cancel")}
              className="rounded-full border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/40">
              Cancel Selected
            </button>
            <button onClick={() => setBulkAction("delete")}
              className="rounded-full border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/40">
              Delete Selected
            </button>
            <button onClick={() => setSelectedIds(new Set())} className="ml-auto text-xs text-blue-600 hover:text-blue-800 dark:text-blue-300 dark:hover:text-blue-100">Clear</button>
          </div>
        )}

      {/* Runs table */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : filteredRuns.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-neutral-300 bg-white p-12 text-center text-neutral-500 shadow-sm dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-400">
          No runs match the current filter.
        </div>
      ) : (
        <>
          <div className="overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <table className="w-full text-sm">
              <thead className="border-b border-neutral-200 bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-800/50">
                <tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-neutral-500 dark:text-neutral-400">
                  <th className="w-10 px-4 py-3" />
                  <th className="px-4 py-3">Procedure</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 min-w-[160px]">Progress</th>
                  <th className="px-4 py-3 whitespace-nowrap">Started</th>
                  <th className="px-4 py-3">Duration</th>
                  <th className="px-4 py-3">Initiated By</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {filteredRuns.map((run) => {
                  const progress = progressFromStatus(run);
                  const isRunning = run.status === "running";
                  const duration = run.duration_seconds != null
                    ? formatDurationSecs(run.duration_seconds)
                    : run.started_at && !run.ended_at
                      ? formatDurationSecs((Date.now() - new Date(run.started_at).getTime()) / 1000)
                      : "—";
                  const progressColor = run.status === "completed" ? "bg-emerald-500" : run.status === "failed" ? "bg-red-400" : run.status === "waiting_approval" ? "bg-amber-400" : "bg-blue-500";
                  return (
                    <tr key={run.run_id} className="group transition-colors hover:bg-neutral-50 dark:hover:bg-neutral-800/40">
                      {/* icon */}
                      <td className="px-4 py-3">
                        <Link href={`/runs/${run.run_id}`}>
                          <div className="flex h-7 w-7 items-center justify-center rounded-full border border-neutral-200 text-neutral-400 transition group-hover:border-sky-300 group-hover:text-sky-600 dark:border-neutral-700">
                            <svg className="h-3 w-3" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                          </div>
                        </Link>
                      </td>
                      {/* Procedure + run-id */}
                      <td className="px-4 py-3">
                        <Link href={`/runs/${run.run_id}`} className="font-medium text-neutral-900 hover:text-sky-600 dark:text-neutral-100 line-clamp-1 text-sm">
                          {run.procedure_id}
                        </Link>
                        <p className="mt-0.5 font-mono text-[11px] text-neutral-400">{run.run_id.slice(0, 8)}&hellip;</p>
                      </td>
                      {/* Status */}
                      <td className="px-4 py-3">
                        <StatusBadge status={run.status} />
                      </td>
                      {/* Progress */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-neutral-100 dark:bg-neutral-800">
                            <div className={`h-full rounded-full transition-all ${progressColor} ${progressWidthClass(progress)} ${isRunning ? "animate-pulse" : ""}`} />
                          </div>
                          <span className="w-9 text-right text-[11px] font-medium text-neutral-500">{progress}%</span>
                        </div>
                      </td>
                      {/* Started */}
                      <td className="px-4 py-3 text-xs text-neutral-500 dark:text-neutral-400 whitespace-nowrap">
                        {formatRelativeTime(run.started_at ?? run.created_at)}
                      </td>
                      {/* Duration */}
                      <td className="px-4 py-3 text-xs text-neutral-500 dark:text-neutral-400 whitespace-nowrap">
                        {duration}
                      </td>
                      {/* Initiated By */}
                      <td className="px-4 py-3 text-xs text-neutral-700 dark:text-neutral-300">
                        {run.triggered_by ?? <span className="text-neutral-300 dark:text-neutral-600">—</span>}
                      </td>
                      {/* Actions */}
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1.5">
                          {(run.status === "running" || run.status === "created") && (
                            <button onClick={() => handleCancel(run.run_id)} title="Stop run"
                              className="flex items-center gap-1 rounded-full border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-600 hover:border-red-200 hover:bg-red-50 hover:text-red-600 dark:border-neutral-700 dark:text-neutral-400">
                              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
                              Stop
                            </button>
                          )}
                          {run.status === "failed" && (
                            <button onClick={() => handleRetry(run.run_id)} title="Retry run"
                              className="flex items-center gap-1 rounded-full border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-600 hover:border-sky-200 hover:bg-sky-50 hover:text-sky-600 dark:border-neutral-700 dark:text-neutral-400">
                              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
                              Retry
                            </button>
                          )}
                          <Link href={`/runs/${run.run_id}`}
                            className="rounded-full border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-400 dark:hover:bg-neutral-800">
                            Details
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {hasMore && (
            <div className="flex justify-center">
              <button onClick={() => { const next = offset + PAGE_SIZE; setOffset(next); void loadRuns(next, true); }}
                className="rounded-full border border-neutral-300 px-6 py-2 text-sm font-medium text-neutral-600 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-400 dark:hover:bg-neutral-800">
                Load more
              </button>
            </div>
          )}
        </>
      )}

      <ConfirmDialog
        open={confirmDeleteId !== null}
        title="Delete Run"
        message="Delete this run and all its events? This cannot be undone."
        confirmLabel="Delete"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setConfirmDeleteId(null)}
      />

      <ConfirmDialog
        open={bulkAction !== null}
        title={bulkAction === "cancel" ? "Bulk Cancel Runs" : "Bulk Delete Runs"}
        message={`${bulkAction === "cancel" ? "Cancel" : "Delete"} ${selectedIds.size} selected run(s)? ${bulkAction === "delete" ? "This cannot be undone." : ""}`}
        confirmLabel={bulkAction === "cancel" ? "Cancel Runs" : "Delete Runs"}
        danger
        onConfirm={executeBulkAction}
        onCancel={() => setBulkAction(null)}
      />
      </div>
    </div>
  );
}

function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 2_592_000_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return `about ${Math.floor(diff / 2_592_000_000)} mo ago`;
}

function formatDurationSecs(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function progressFromStatus(run: Run): number {
  switch (run.status) {
    case "completed": return 100;
    case "failed": return 65;
    case "cancelled":
    case "canceled": return 50;
    case "running": return 70;
    case "waiting_approval": return 75;
    case "pending": return 10;
    case "created": return 5;
    default: return 0;
  }
}

function progressWidthClass(p: number): string {
  // Discrete map so Tailwind JIT can statically detect all classes
  if (p >= 100) return "w-full";
  if (p >= 75) return "w-[75%]";
  if (p >= 70) return "w-[70%]";
  if (p >= 65) return "w-[65%]";
  if (p >= 50) return "w-1/2";
  if (p >= 10) return "w-[10%]";
  return "w-[5%]";
}

