"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listApprovals, submitApprovalDecision } from "@/lib/api";
import type { Approval } from "@/lib/types";

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "pending">("pending");

  useEffect(() => {
    loadApprovals();
  }, []);

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

  async function handleDecision(
    approvalId: string,
    decision: "approved" | "rejected"
  ) {
    try {
      await submitApprovalDecision(approvalId, decision, "ui_user");
      loadApprovals();
    } catch (err) {
      console.error(err);
    }
  }

  const filtered =
    filter === "all" ? approvals : approvals.filter((a) => a.status === "pending");

  const pendingCount = approvals.filter((a) => a.status === "pending").length;

  return (
    <div className="space-y-6">
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

function ApprovalStatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    pending: "badge-warning",
    approved: "badge-success",
    rejected: "badge-error",
    timed_out: "badge-neutral",
  };
  return <span className={`badge ${cls[status] ?? "badge-neutral"}`}>{status}</span>;
}
