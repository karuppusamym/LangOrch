"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getApproval, submitApprovalDecision } from "@/lib/api";
import { ApprovalStatusBadge } from "@/components/shared/ApprovalStatusBadge";
import { useToast } from "@/components/Toast";
import type { Approval } from "@/lib/types";

export default function ApprovalDetailPage() {
  const params = useParams();
  const approvalId = params.id as string;
  const { toast } = useToast();

  const [approval, setApproval] = useState<Approval | null>(null);
  const [loading, setLoading] = useState(true);
  const [comment, setComment] = useState("");
  const [approverName, setApproverName] = useState(() =>
    typeof window !== "undefined" ? (localStorage.getItem("approver_name") ?? "") : ""
  );

  function saveApproverName(name: string) {
    setApproverName(name);
    if (typeof window !== "undefined") localStorage.setItem("approver_name", name);
  }

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
        approverName.trim() || "ui_user",
        comment || undefined
      );
      setApproval(updated);
      toast(`Approval ${decision}`, "success");
    } catch (err) {
      console.error(err);
      toast("Decision failed", "error");
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
          {approval.expires_at && approval.status === "pending" && (
            <CountdownBadge expiresAt={approval.expires_at} />
          )}
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

        {/* Context data */}
        {approval.context_data && Object.keys(approval.context_data).length > 0 && (
          <div className="mt-6 rounded-lg border border-blue-100 bg-blue-50 p-4">
            <h3 className="mb-2 text-xs font-semibold text-blue-700">Context Data</h3>
            <div className="space-y-1.5">
              {Object.entries(approval.context_data).map(([k, v]) => (
                <div key={k} className="flex gap-2 text-xs">
                  <span className="font-medium text-blue-600 min-w-[100px]">{k}:</span>
                  <span className="text-blue-800 break-all">
                    {typeof v === "object" ? JSON.stringify(v, null, 2) : String(v)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Decision options */}
        {approval.options && approval.options.length > 0 && (
          <div className="mt-4 rounded-lg border border-gray-100 bg-gray-50 p-4">
            <h3 className="mb-2 text-xs font-semibold text-gray-700">Available Options</h3>
            <div className="flex flex-wrap gap-2">
              {approval.options.map((opt) => (
                <span key={opt} className="rounded-full bg-white px-3 py-1 text-xs font-medium text-gray-700 border border-gray-200">{opt}</span>
              ))}
            </div>
          </div>
        )}

        {approval.status === "pending" && (
          <div className="mt-8 space-y-4 border-t border-gray-200 pt-6">
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500 shrink-0">Your name:</label>
              <input
                value={approverName}
                onChange={(e) => saveApproverName(e.target.value)}
                placeholder="approver name (persisted)"
                className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs focus:border-primary-400 focus:outline-none w-56"
              />
            </div>
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

