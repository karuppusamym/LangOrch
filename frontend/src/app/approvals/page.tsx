"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { listApprovals, submitApprovalDecision } from "@/lib/api";
import { subscribeToApprovalUpdates } from "@/lib/sse";
import { ApprovalStatusBadge } from "@/components/shared/ApprovalStatusBadge";
import { useToast } from "@/components/Toast";
import type { Approval } from "@/lib/types";

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "pending">("pending");
  const [approverName, setApproverName] = useState(() =>
    typeof window !== "undefined" ? (localStorage.getItem("approver_name") ?? "") : ""
  );
  const { toast } = useToast();

  async function loadApprovals() {
    try {
      const data = await listApprovals();
      setApprovals(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadApprovals();
    // SSE subscription for real-time approval updates
    const cleanup = subscribeToApprovalUpdates(
      (_update) => {
        // Re-fetch full list when any approval changes
        loadApprovals();
      },
      () => {
        // On SSE error, fall back to polling
        console.warn("Approval SSE disconnected, falling back to polling");
      }
    );
    return cleanup;
  }, []);

  function saveApproverName(name: string) {
    setApproverName(name);
    if (typeof window !== "undefined") localStorage.setItem("approver_name", name);
  }

  async function handleDecision(
    approvalId: string,
    decision: "approved" | "rejected"
  ) {
    try {
      await submitApprovalDecision(approvalId, decision, approverName.trim() || "ui_user");
      toast(`Approval ${decision}`, "success");
      loadApprovals();
    } catch (err) {
      console.error(err);
      toast("Decision failed", "error");
    }
  }

  const filtered =
    filter === "all" ? approvals : approvals.filter((a) => a.status === "pending");

  const pendingCount = approvals.filter((a) => a.status === "pending").length;

  return (
    <div className="space-y-6">
      {/* Pending pulse indicator */}
      {pendingCount > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-yellow-200 bg-yellow-50 px-4 py-2 text-sm text-yellow-800">
          <span className="relative flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-yellow-400 opacity-75" />
            <span className="relative inline-flex h-3 w-3 rounded-full bg-yellow-500" />
          </span>
          {pendingCount} approval{pendingCount > 1 ? "s" : ""} waiting
        </div>
      )}

      {/* Filter */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => setFilter("pending")}
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            filter === "pending"
              ? "bg-yellow-100 text-yellow-800"
              : "bg-gray-100 text-gray-600"
          }`}
        >
          Pending ({pendingCount})
        </button>
        <button
          onClick={() => setFilter("all")}
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            filter === "all"
              ? "bg-primary-100 text-primary-800"
              : "bg-gray-100 text-gray-600"
          }`}
        >
          All ({approvals.length})
        </button>
        <span className="ml-auto text-[10px] text-gray-400">Live (SSE)</span>
      </div>

      {/* Approver name */}
      <div className="flex items-center gap-2">
        <label className="text-xs text-gray-500 shrink-0">Your name:</label>
        <input
          value={approverName}
          onChange={(e) => saveApproverName(e.target.value)}
          placeholder="approver name (persisted)"
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs focus:border-primary-400 focus:outline-none w-56"
        />
      </div>

      {/* Approval list */}
      {loading ? (
        <p className="text-gray-500">Loading approvals...</p>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 p-12 text-center text-gray-400">
          {filter === "pending"
            ? "No pending approvals — all caught up!"
            : "No approvals found."}
        </div>
      ) : (
        <div className="space-y-4">
          {filtered.map((approval) => (
            <div
              key={approval.approval_id}
              className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <ApprovalStatusBadge status={approval.status} />
                    <span className="text-xs text-gray-400">
                      Node: {approval.node_id}
                    </span>
                    {approval.expires_at && approval.status === "pending" && (
                      <CountdownBadge expiresAt={approval.expires_at} />
                    )}
                  </div>
                  <p className="mt-2 text-sm text-gray-900">{approval.prompt}</p>
                  <p className="mt-1 text-xs text-gray-400">
                    Run:{" "}
                    <Link
                      href={`/runs/${approval.run_id}`}
                      className="text-primary-600 hover:underline"
                    >
                      {approval.run_id.slice(0, 8)}…
                    </Link>
                    {" · "}
                    {new Date(approval.created_at).toLocaleString()}
                  </p>
                  {approval.decided_by && (
                    <p className="mt-1 text-xs text-gray-400">
                      Decided by: {approval.decided_by} at{" "}
                      {approval.decided_at
                        ? new Date(approval.decided_at).toLocaleString()
                        : "—"}
                    </p>
                  )}
                </div>

                {approval.status === "pending" && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleDecision(approval.approval_id, "approved")}
                      className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => handleDecision(approval.approval_id, "rejected")}
                      className="rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
                    >
                      Reject
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CountdownBadge({ expiresAt }: { expiresAt: string }) {
  const [remaining, setRemaining] = useState("");
  useEffect(() => {
    function tick() {
      const diff = new Date(expiresAt).getTime() - Date.now();
      if (diff <= 0) { setRemaining("expired"); return; }
      const m = Math.floor(diff / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      setRemaining(`${m}m ${s}s`);
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);
  const isUrgent = remaining !== "expired" && new Date(expiresAt).getTime() - Date.now() < 120_000;
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${isUrgent ? "bg-red-100 text-red-600 animate-pulse" : "bg-gray-100 text-gray-500"}`}>
      ⏱ {remaining}
    </span>
  );
}

