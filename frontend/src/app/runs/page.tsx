"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { cleanupRuns, deleteRun, listRuns, cancelRun } from "@/lib/api";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/shared/StatusBadge";
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
  const PAGE_SIZE = 100;

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
    <div className="space-y-6">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        {["all", "created", "running", "waiting_approval", "completed", "failed", "canceled"].map(
          (s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                filter === s
                  ? "bg-primary-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {s === "all" ? `All (${runs.length})` : `${s} (${statusCounts[s] || 0})`}
            </button>
          )
        )}

        <select
          value={order}
          onChange={(e) => setOrder(e.target.value as "asc" | "desc")}
          className="ml-2 rounded-md border border-gray-300 px-2 py-1 text-xs"
          title="Order"
        >
          <option value="desc">Newest first</option>
          <option value="asc">Oldest first</option>
        </select>

        <input
          type="date"
          value={createdFrom}
          onChange={(e) => setCreatedFrom(e.target.value)}
          className="rounded-md border border-gray-300 px-2 py-1 text-xs"
          title="Created from"
        />
        <input
          type="date"
          value={createdTo}
          onChange={(e) => setCreatedTo(e.target.value)}
          className="rounded-md border border-gray-300 px-2 py-1 text-xs"
          title="Created to"
        />
        <button
          onClick={() => { setOffset(0); void loadRuns(0); }}
          className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
        >
          Refresh
        </button>

        <div className="ml-3 flex items-center gap-1">
          <span className="text-xs text-gray-400">Quick:</span>
          <button
            onClick={() => applyPreset(1)}
            className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
          >
            Last 24h
          </button>
          <button
            onClick={() => applyPreset(7)}
            className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
          >
            Last 7d
          </button>
          <button
            onClick={() => applyPreset(30)}
            className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
          >
            Last 30d
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white p-3">
        <span className="text-xs text-gray-500">Cleanup runs before:</span>
        <input
          type="date"
          value={cleanupBefore}
          onChange={(e) => setCleanupBefore(e.target.value)}
          className="rounded-md border border-gray-300 px-2 py-1 text-xs"
          title="Cleanup before date"
        />
        <button
          onClick={handlePreviewCleanup}
          disabled={!cleanupBefore}
          className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100 disabled:opacity-50"
        >
          Preview
        </button>
        <button
          onClick={handleCleanup}
          disabled={!cleanupBefore}
          className="rounded-md border border-red-300 px-2 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
        >
          Cleanup
        </button>
        {cleanupPreviewCount !== null && (
          <span className="text-xs text-gray-500">Will delete ~{cleanupPreviewCount} run(s)</span>
        )}
      </div>

      {/* Runs table */}
      {loading ? (
        <p className="text-gray-500">Loading runs...</p>
      ) : filteredRuns.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 p-12 text-center text-gray-400">
          No runs match the current filter.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-gray-500">
                <th className="px-6 py-3 font-medium">Run ID</th>
                <th className="px-6 py-3 font-medium">Procedure</th>
                <th className="px-6 py-3 font-medium">Version</th>
                <th className="px-6 py-3 font-medium">Status</th>
                <th className="px-6 py-3 font-medium">Created</th>
                <th className="px-6 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filteredRuns.map((run) => (
                <tr key={run.run_id} className="hover:bg-gray-50">
                  <td className="px-6 py-3">
                    <Link
                      href={`/runs/${run.run_id}`}
                      className="font-mono text-primary-600 hover:underline"
                    >
                      {run.run_id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="px-6 py-3 text-gray-700">{run.procedure_id}</td>
                  <td className="px-6 py-3 text-gray-400">v{run.procedure_version}</td>
                  <td className="px-6 py-3">
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="px-6 py-3 text-gray-400">
                    {new Date(run.created_at).toLocaleString()}
                  </td>
                  <td className="px-6 py-3">
                    {(run.status === "running" || run.status === "created") && (
                      <button
                        onClick={() => handleCancel(run.run_id)}
                        className="text-xs text-red-600 hover:underline"
                      >
                        Cancel
                      </button>
                    )}
                    {run.status !== "running" && (
                      <button
                        onClick={() => handleDelete(run.run_id)}
                        className="ml-3 text-xs text-gray-500 hover:underline"
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {hasMore && (
        <div className="flex justify-center pt-2">
          <button
            onClick={() => {
              const next = offset + PAGE_SIZE;
              setOffset(next);
              void loadRuns(next, true);
            }}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
          >
            Load more
          </button>
        </div>
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
    </div>
  );
}

