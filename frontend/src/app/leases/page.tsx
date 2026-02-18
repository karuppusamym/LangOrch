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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Active Leases</h2>
          <p className="mt-1 text-sm text-gray-500">
            Resource locks held by running steps. Auto-refreshes every 10 s.
          </p>
        </div>
        <button
          onClick={load}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Refresh
        </button>
      </div>

      {loading ? (
        <p className="text-gray-500">Loading leases…</p>
      ) : leases.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 p-12 text-center text-gray-400">
          No active leases — all resources are free.
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-gray-50 text-left text-xs font-semibold text-gray-500">
                <th className="px-4 py-3">Resource Key</th>
                <th className="px-4 py-3">Run ID</th>
                <th className="px-4 py-3">Node / Step</th>
                <th className="px-4 py-3">Acquired</th>
                <th className="px-4 py-3">Expires</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {leases.map((lease) => {
                const expiresSoon =
                  new Date(lease.expires_at).getTime() - Date.now() < 30_000;
                return (
                  <tr
                    key={lease.lease_id}
                    className="border-b last:border-0 hover:bg-gray-50"
                  >
                    <td className="px-4 py-3 font-mono font-medium text-gray-900">
                      {lease.resource_key}
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      <a
                        href={`/runs/${lease.run_id}`}
                        className="text-primary-600 hover:underline"
                      >
                        {lease.run_id.slice(0, 10)}…
                      </a>
                    </td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">
                      {lease.node_id ?? "—"}
                      {lease.step_id ? ` / ${lease.step_id}` : ""}
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {new Date(lease.acquired_at).toLocaleTimeString()}
                    </td>
                    <td className={`px-4 py-3 text-xs ${expiresSoon ? "text-red-500 font-medium" : "text-gray-400"}`}>
                      {new Date(lease.expires_at).toLocaleTimeString()}
                      {expiresSoon && " ⚠"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => handleRevoke(lease.lease_id, lease.resource_key)}
                        disabled={revoking === lease.lease_id}
                        className="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                      >
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
