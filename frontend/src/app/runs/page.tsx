"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { cleanupRuns, deleteRun, listRuns, cancelRun } from "@/lib/api";
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

  const filteredRuns =
    filter === "all" ? runs : runs.filter((r) => r.status === filter);

  const statusCounts = runs.reduce(
    (acc, r) => {
      acc[r.status] = (acc[r.status] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">Workflow Runs</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">Monitor and manage procedure executions</p>
        </div>
        <button
          onClick={() => { setOffset(0); void loadRuns(0); }}
          className="flex items-center gap-2 rounded-lg border border-neutral-300 dark:border-neutral-700 px-4 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
            <input
              type="search"
              placeholder="Search runs..."
              className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 pl-9 pr-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 focus:border-blue-500 focus:outline-none"
              readOnly
            />
          </div>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 focus:border-blue-500 focus:outline-none"
          >
            <option value="all">All Status</option>
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
            className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 focus:border-blue-500 focus:outline-none"
          >
            <option value="desc">Newest first</option>
            <option value="asc">Oldest first</option>
          </select>
          <input type="date" value={createdFrom} onChange={(e) => setCreatedFrom(e.target.value)} title="From date"
            className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 focus:border-blue-500 focus:outline-none" />
          <input type="date" value={createdTo} onChange={(e) => setCreatedTo(e.target.value)} title="To date"
            className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 focus:border-blue-500 focus:outline-none" />
          <div className="flex items-center gap-1.5 ml-1">
            {[1, 7, 30].map((d) => (
              <button key={d} onClick={() => applyPreset(d)}
                className="rounded-md border border-neutral-200 dark:border-neutral-700 px-2.5 py-1.5 text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800">
                {d === 1 ? "24h" : `${d}d`}
              </button>
            ))}
          </div>
        </div>
        {/* Cleanup row */}
        <div className="mt-3 flex flex-wrap items-center gap-2 pt-3 border-t border-neutral-100 dark:border-neutral-800">
          <span className="text-xs text-neutral-500">Cleanup before:</span>
          <input type="date" value={cleanupBefore} onChange={(e) => setCleanupBefore(e.target.value)} title="Cleanup before"
            className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-2.5 py-1.5 text-xs text-neutral-700 dark:text-neutral-300 focus:border-blue-500 focus:outline-none" />
          <button onClick={handlePreviewCleanup} disabled={!cleanupBefore}
            className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-2.5 py-1.5 text-xs text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800 disabled:opacity-40">
            Preview
          </button>
          <button onClick={handleCleanup} disabled={!cleanupBefore}
            className="rounded-lg border border-red-200 dark:border-red-900 px-2.5 py-1.5 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-40">
            Cleanup
          </button>
          {cleanupPreviewCount !== null && (
            <span className="text-xs text-neutral-400">~{cleanupPreviewCount} run(s) will be deleted</span>
          )}
        </div>
      </div>

      {/* Bulk action bar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/30 px-4 py-2">
          <span className="text-sm font-medium text-blue-700 dark:text-blue-400">{selectedIds.size} selected</span>
          <button onClick={() => setBulkAction("cancel")}
            className="rounded-md border border-red-300 dark:border-red-800 px-3 py-1 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950">
            Cancel Selected
          </button>
          <button onClick={() => setBulkAction("delete")}
            className="rounded-md border border-red-300 dark:border-red-800 px-3 py-1 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950">
            Delete Selected
          </button>
          <button onClick={() => setSelectedIds(new Set())} className="ml-auto text-xs text-neutral-500 hover:text-neutral-700">Clear</button>
        </div>
      )}

      {/* Runs table */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : filteredRuns.length === 0 ? (
        <div className="rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 p-16 text-center text-neutral-400">
          No runs match the current filter.
        </div>
      ) : (
        <>
          <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 overflow-hidden shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 dark:bg-neutral-800/50 border-b border-neutral-200 dark:border-neutral-700">
                <tr className="text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                  <th className="px-4 py-3">
                    <input type="checkbox" title="Select all"
                      checked={filteredRuns.length > 0 && selectedIds.size === filteredRuns.length}
                      onChange={toggleSelectAll} className="rounded" />
                  </th>
                  <th className="px-4 py-3">Run ID</th>
                  <th className="px-4 py-3">Procedure</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Created</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {filteredRuns.map((run) => (
                  <tr key={run.run_id} className={`hover:bg-neutral-50 dark:hover:bg-neutral-800/50 transition-colors ${selectedIds.has(run.run_id) ? "bg-blue-50/50 dark:bg-blue-950/20" : ""}`}>
                    <td className="px-4 py-3">
                      <input type="checkbox" aria-label={`Select run ${run.run_id}`}
                        checked={selectedIds.has(run.run_id)}
                        onChange={() => toggleSelect(run.run_id)} className="rounded" />
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/runs/${run.run_id}`} className="font-mono text-blue-600 dark:text-blue-400 hover:underline text-xs">
                        {run.run_id.slice(0, 8)}…
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/procedures/${encodeURIComponent(run.procedure_id)}`} className="text-xs font-medium text-neutral-900 dark:text-neutral-100 hover:text-blue-600 dark:hover:text-blue-400">
                        {run.procedure_id}
                      </Link>
                      <span className="ml-1.5 text-[10px] text-neutral-400">v{run.procedure_version}</span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-3 text-xs text-neutral-500 dark:text-neutral-400">
                      {new Date(run.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {(run.status === "running" || run.status === "created") && (
                          <button onClick={() => handleCancel(run.run_id)}
                            className="rounded-md border border-red-200 dark:border-red-800 px-2.5 py-1 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950">
                            Stop
                          </button>
                        )}
                        {run.status !== "running" && (
                          <button onClick={() => handleDelete(run.run_id)}
                            className="rounded-md border border-neutral-200 dark:border-neutral-700 px-2.5 py-1 text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800">
                            Delete
                          </button>
                        )}
                        <Link href={`/runs/${run.run_id}`}
                          className="rounded-md border border-neutral-200 dark:border-neutral-700 px-2.5 py-1 text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800">
                          Details
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {hasMore && (
            <div className="flex justify-center">
              <button onClick={() => { const next = offset + PAGE_SIZE; setOffset(next); void loadRuns(next, true); }}
                className="rounded-lg border border-neutral-300 dark:border-neutral-700 px-6 py-2 text-sm font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800">
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
  );
}

