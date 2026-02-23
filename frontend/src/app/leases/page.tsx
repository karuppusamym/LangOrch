"use client";

import { useEffect, useState, useCallback } from "react";
import { listLeases, revokeLease } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { ResourceLeaseDiagnostic } from "@/lib/types";

export default function LeasesPage() {
  const { toast } = useToast();
  const [leases, setLeases] = useState<ResourceLeaseDiagnostic[]>([]);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState<{ leaseId: string; resourceKey: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await listLeases();
      setLeases(data);
    } catch {
      toast("Failed to load leases", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [load]);

  async function handleRevoke(leaseId: string, resourceKey: string) {
    setConfirmRevoke({ leaseId, resourceKey });
  }

  async function doRevoke() {
    if (!confirmRevoke) return;
    const { leaseId, resourceKey } = confirmRevoke;
    setConfirmRevoke(null);
    setRevoking(leaseId);
    try {
      await revokeLease(leaseId);
      toast(`Lease released: ${resourceKey}`, "success");
      await load();
    } catch {
      toast("Failed to release lease", "error");
    } finally {
      setRevoking(null);
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">Resources</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">Active resource leases held by running workflow steps</p>
        </div>
        <button onClick={load}
          className="flex items-center gap-2 rounded-lg border border-neutral-300 dark:border-neutral-700 px-4 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
          Refresh
        </button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5 shadow-sm">
          <p className="text-sm text-neutral-500 dark:text-neutral-400">Active Leases</p>
          <p className="mt-1 text-3xl font-bold text-blue-600">{leases.length}</p>
        </div>
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5 shadow-sm">
          <p className="text-sm text-neutral-500 dark:text-neutral-400">Expiring Soon</p>
          <p className="mt-1 text-3xl font-bold text-amber-600">{leases.filter(l => new Date(l.expires_at).getTime() - Date.now() < 30_000).length}</p>
        </div>
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5 shadow-sm flex items-center gap-3">
          <div>
            <p className="text-sm text-neutral-500 dark:text-neutral-400">System Health</p>
            <p className="mt-1 text-sm font-semibold text-green-600">{leases.length === 0 ? "All Free" : "In Use"}</p>
          </div>
          <div className={`ml-auto h-3 w-3 rounded-full ${leases.length === 0 ? "bg-green-500" : "bg-amber-500"}`} />
        </div>
      </div>

      {/* Lease table */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : leases.length === 0 ? (
        <div className="rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 p-16 text-center text-neutral-400">
          <svg className="w-12 h-12 mx-auto mb-3 text-neutral-300 dark:text-neutral-700" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" /></svg>
          No active leases — all resources are free.
        </div>
      ) : (
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-800/50 border-b border-neutral-200 dark:border-neutral-700">
              <tr className="text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                <th className="px-4 py-3">Resource Key</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Run</th>
                <th className="px-4 py-3">Node / Step</th>
                <th className="px-4 py-3">Acquired</th>
                <th className="px-4 py-3">Expires</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {leases.map((lease) => {
                const expiresSoon = new Date(lease.expires_at).getTime() - Date.now() < 30_000;
                return (
                  <tr key={lease.lease_id} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/50 transition-colors">
                    <td className="px-4 py-3">
                      <code className="rounded bg-neutral-100 dark:bg-neutral-800 px-1.5 py-0.5 text-xs font-mono text-neutral-800 dark:text-neutral-200">
                        {lease.resource_key}
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-full bg-blue-50 dark:bg-blue-950/50 border border-blue-200 dark:border-blue-800 px-2 py-0.5 text-xs text-blue-700 dark:text-blue-400">
                        {lease.resource_key.split("_")[0] || "lock"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {lease.run_id ? (
                        <a href={`/runs/${lease.run_id}`} className="font-mono text-xs text-blue-600 dark:text-blue-400 hover:underline">
                          {lease.run_id.slice(0, 10)}…
                        </a>
                      ) : <span className="text-neutral-400">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-neutral-500 dark:text-neutral-400">
                      {lease.node_id ?? "—"}{lease.step_id ? ` / ${lease.step_id}` : ""}
                    </td>
                    <td className="px-4 py-3 text-xs text-neutral-400">{new Date(lease.acquired_at).toLocaleTimeString()}</td>
                    <td className={`px-4 py-3 text-xs font-medium ${expiresSoon ? "text-red-500 dark:text-red-400" : "text-neutral-400"}`}>
                      {new Date(lease.expires_at).toLocaleTimeString()}
                      {expiresSoon && <span className="ml-1 text-[10px] animate-pulse">⚠ expiring</span>}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button onClick={() => handleRevoke(lease.lease_id, lease.resource_key)}
                        disabled={revoking === lease.lease_id}
                        className="rounded-md border border-red-200 dark:border-red-800 px-3 py-1 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-50">
                        {revoking === lease.lease_id ? "Releasing…" : "Force Release"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={confirmRevoke !== null}
        title="Force-Release Lease"
        message={confirmRevoke ? `Force-release the lease on "${confirmRevoke.resourceKey}"? The associated step may encounter an error.` : ""}
        confirmLabel="Release"
        danger
        onConfirm={doRevoke}
        onCancel={() => setConfirmRevoke(null)}
      />
    </div>
  );
}
