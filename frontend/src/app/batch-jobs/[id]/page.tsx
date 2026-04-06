"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  cancelBatchJob,
  cancelBatchJobItem,
  exportFailedBatchJobItems,
  getBatchJob,
  isNotFoundError,
  listBatchJobItems,
  retryBatchJobItem,
  retryFailedBatchJobItems,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { BatchJob, BatchJobItem } from "@/lib/types";

function fmtDate(value: string | null | undefined) {
  if (!value) return "-";
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? value : dt.toLocaleString();
}

export default function BatchJobDetailPage() {
  const params = useParams();
  const batchJobId = params.id as string;
  const { toast } = useToast();

  const [job, setJob] = useState<BatchJob | null>(null);
  const [items, setItems] = useState<BatchJobItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [jobRow, itemRows] = await Promise.all([
        getBatchJob(batchJobId),
        listBatchJobItems(batchJobId),
      ]);
      setJob(jobRow);
      setItems(itemRows);
    } catch (err) {
      if (isNotFoundError(err)) {
        setJob(null);
        setItems([]);
        return;
      }
      toast(err instanceof Error ? err.message : "Failed to load batch job", "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [batchJobId]);

  async function handleRetryItem(itemId: string) {
    setWorking(itemId);
    try {
      await retryBatchJobItem(batchJobId, itemId);
      toast("Batch row requeued", "success");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to retry batch row", "error");
    } finally {
      setWorking(null);
    }
  }

  async function handleCancelItem(itemId: string) {
    setWorking(itemId);
    try {
      await cancelBatchJobItem(batchJobId, itemId);
      toast("Batch row cancelled", "success");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to cancel batch row", "error");
    } finally {
      setWorking(null);
    }
  }

  async function handleRetryFailed() {
    setWorking("retry-failed");
    try {
      const result = await retryFailedBatchJobItems(batchJobId);
      toast(result.affected > 0 ? `Requeued ${result.affected} failed row(s)` : "No failed rows to requeue", result.affected > 0 ? "success" : "warning");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to retry failed rows", "error");
    } finally {
      setWorking(null);
    }
  }

  async function handleCancelBatch() {
    setWorking("cancel-batch");
    try {
      const result = await cancelBatchJob(batchJobId);
      toast(result.affected > 0 ? `Cancelled ${result.affected} active row(s)` : "No active rows to cancel", result.affected > 0 ? "success" : "warning");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to cancel batch job", "error");
    } finally {
      setWorking(null);
    }
  }

  async function handleExportFailed() {
    setWorking("export-failed");
    try {
      const csv = await exportFailedBatchJobItems(batchJobId);
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${batchJobId}-failed-rows.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to export failed rows", "error");
    } finally {
      setWorking(null);
    }
  }

  if (loading) return <div className="p-6 text-sm text-neutral-500">Loading batch job...</div>;
  if (!job) return <div className="p-6 text-sm text-red-600">Batch job not found.</div>;

  const failedItems = items.filter((item) => item.status === "failed");
  const activeItems = items.filter((item) => ["created", "pending", "running", "waiting_approval"].includes(item.status));

  return (
    <div className="min-h-[calc(100vh-4rem)] space-y-4 bg-neutral-50 p-6">
      <section className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <Link href="/batch-jobs" className="text-sm text-blue-600 hover:underline">← Batch Jobs</Link>
            <h1 className="mt-1 text-2xl font-semibold text-neutral-900 dark:text-neutral-100">{job.name}</h1>
            <p className="font-mono text-xs text-neutral-500">{job.batch_job_id}</p>
          </div>
          <button onClick={() => void load()} className="rounded-full border border-neutral-200 px-4 py-2 text-sm font-medium hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800">
            Refresh
          </button>
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-5">
        {[
          ["Status", job.status],
          ["Queued", String(job.queued_items)],
          ["Running", String(job.running_items)],
          ["Completed", String(job.completed_items)],
          ["Failed", `${job.failed_items}${job.canceled_items > 0 ? ` / ${job.canceled_items} canceled` : ""}`],
        ].map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <p className="text-xs uppercase tracking-wide text-neutral-400">{label}</p>
            <p className="mt-2 text-lg font-semibold text-neutral-900 dark:text-neutral-100">{value}</p>
          </div>
        ))}
      </section>

      <section className="grid gap-3 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
          <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Batch Controls</h2>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              onClick={() => void handleRetryFailed()}
              disabled={working !== null || failedItems.length === 0}
              className="rounded-full bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Requeue Failed Rows
            </button>
            <button
              onClick={() => void handleCancelBatch()}
              disabled={working !== null || activeItems.length === 0}
              className="rounded-full border border-amber-300 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-50"
            >
              Cancel Active Rows
            </button>
            <button
              onClick={() => void handleExportFailed()}
              disabled={working !== null || failedItems.length === 0}
              className="rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
            >
              Export Failed Rows
            </button>
          </div>
        </div>

        <div className="rounded-2xl border border-neutral-200 bg-white p-5 text-sm shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
          <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Batch Metadata</h2>
          <div className="mt-3 space-y-1 text-xs text-neutral-600 dark:text-neutral-300">
            <p>Procedure: {job.procedure_id} v{job.procedure_version}</p>
            <p>Source: {job.source_format}</p>
            <p>Case creation: {job.create_case_per_item ? "one case per row" : "runs only"}</p>
            <p>Case type: {job.case_type ?? "-"}</p>
            <p>Triggered by: {job.triggered_by ?? "-"}</p>
            <p>Created: {fmtDate(job.created_at)}</p>
            <p>Completed: {fmtDate(job.completed_at)}</p>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-neutral-200 bg-white shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="border-b border-neutral-100 px-5 py-3 text-sm font-semibold dark:border-neutral-800">
          Batch Rows ({items.length})
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500 dark:bg-neutral-800/50">
              <tr>
                <th className="px-4 py-3">Row</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Run</th>
                <th className="px-4 py-3">Case</th>
                <th className="px-4 py-3">Input</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {items.map((item) => {
                const canRetry = item.status === "failed" || item.status === "canceled" || item.status === "cancelled";
                const canCancel = ["created", "pending", "running", "waiting_approval"].includes(item.status);
                return (
                  <tr key={item.item_id}>
                    <td className="px-4 py-3 text-xs">
                      <p className="font-medium text-neutral-900 dark:text-neutral-100">#{item.item_index + 1}</p>
                      <p className="font-mono text-neutral-500">{item.item_id.slice(0, 12)}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-full bg-neutral-100 px-2 py-1 text-xs dark:bg-neutral-800">{item.status}</span>
                      {item.error_message ? <p className="mt-1 max-w-xs text-[11px] text-red-600">{item.error_message}</p> : null}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {item.run_id ? (
                        <Link href={`/runs/${item.run_id}`} className="font-mono text-sky-600 hover:underline">
                          {item.run_id.slice(0, 12)}
                        </Link>
                      ) : "-"}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {item.case_id ? (
                        <Link href={`/cases/${item.case_id}`} className="font-mono text-sky-600 hover:underline">
                          {item.case_id.slice(0, 12)}
                        </Link>
                      ) : "-"}
                    </td>
                    <td className="px-4 py-3 text-[11px] text-neutral-600 dark:text-neutral-300">
                      <pre className="max-w-sm overflow-auto rounded bg-neutral-50 p-2 dark:bg-neutral-800">
                        {JSON.stringify(item.input_vars ?? {}, null, 2)}
                      </pre>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => void handleRetryItem(item.item_id)}
                          disabled={working !== null || !canRetry}
                          className="rounded-full border border-blue-300 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                        >
                          Retry
                        </button>
                        <button
                          onClick={() => void handleCancelItem(item.item_id)}
                          disabled={working !== null || !canCancel}
                          className="rounded-full border border-amber-300 px-3 py-1 text-xs font-medium text-amber-800 hover:bg-amber-50 disabled:opacity-50"
                        >
                          Cancel
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
