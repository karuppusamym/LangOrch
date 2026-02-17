"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getApproval, submitApprovalDecision } from "@/lib/api";
import type { Approval } from "@/lib/types";

export default function ApprovalDetailPage() {
  const params = useParams();
  const approvalId = params.id as string;

  const [approval, setApproval] = useState<Approval | null>(null);
  const [loading, setLoading] = useState(true);
  const [comment, setComment] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const data = await getApproval(approvalId);
        setApproval(data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [approvalId]);

  async function handleDecision(decision: "approved" | "rejected") {
    try {
      const updated = await submitApprovalDecision(
        approvalId,
        decision,
        "ui_user",
        comment || undefined
      );
      setApproval(updated);
    } catch (err) {
      console.error(err);
    }
  }

  if (loading) return <p className="text-gray-500">Loading approval...</p>;
  if (!approval) return <p className="text-red-500">Approval not found</p>;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Link href="/approvals" className="text-sm text-primary-600 hover:underline">
        ← Approvals
      </Link>

      <div className="rounded-xl border border-gray-200 bg-white p-8 shadow-sm">
        <div className="mb-6 flex items-center gap-3">
          <ApprovalStatusBadge status={approval.status} />
          <span className="text-xs text-gray-400">ID: {approval.approval_id.slice(0, 12)}…</span>
        </div>

        <h2 className="text-lg font-semibold text-gray-900">{approval.prompt}</h2>

        <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-500">Run: </span>
            <Link href={`/runs/${approval.run_id}`} className="text-primary-600 hover:underline">
              {approval.run_id.slice(0, 12)}…
            </Link>
          </div>
          <div>
            <span className="text-gray-500">Node: </span>
            <span className="font-mono">{approval.node_id}</span>
          </div>
          <div>
            <span className="text-gray-500">Created: </span>
            {new Date(approval.created_at).toLocaleString()}
          </div>
          {approval.decided_by && (
            <div>
              <span className="text-gray-500">Decided by: </span>
              {approval.decided_by}
            </div>
          )}
        </div>

        {approval.status === "pending" && (
          <div className="mt-8 space-y-4 border-t border-gray-200 pt-6">
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Optional comment..."
              className="w-full rounded-lg border border-gray-300 p-3 text-sm focus:border-primary-500 focus:outline-none"
              rows={3}
            />
            <div className="flex gap-3">
              <button
                onClick={() => handleDecision("approved")}
                className="flex-1 rounded-lg bg-green-600 py-2.5 text-sm font-medium text-white hover:bg-green-700"
              >
                Approve
              </button>
              <button
                onClick={() => handleDecision("rejected")}
                className="flex-1 rounded-lg border border-red-300 py-2.5 text-sm font-medium text-red-600 hover:bg-red-50"
              >
                Reject
              </button>
            </div>
          </div>
        )}
      </div>
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
