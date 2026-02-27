"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { listApprovals, submitApprovalDecision } from "@/lib/api";
import { subscribeToApprovalUpdates } from "@/lib/sse";
import { ApprovalStatusBadge } from "@/components/shared/ApprovalStatusBadge";
import { useToast } from "@/components/Toast";
import { getUser } from "@/lib/auth";
import type { Approval } from "@/lib/types";

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "pending">("pending");
  const [activeApproval, setActiveApproval] = useState<Approval | null>(null);
  const [decisionType, setDecisionType] = useState<"approved" | "rejected" | null>(null);
  const [comment, setComment] = useState("");
  const [approverName, setApproverName] = useState(() => {
    // Prefer authenticated user identity; fall back to any stored preference
    const user = getUser();
    if (user?.identity) return user.identity;
    if (typeof window !== "undefined") return localStorage.getItem("approver_name") ?? "";
    return "";
  });
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
      await submitApprovalDecision(approvalId, decision, approverName.trim() || "ui_user", comment || undefined);
      toast(`Approval ${decision}`, "success");
      loadApprovals();
    } catch (err) {
      console.error(err);
      toast("Decision failed", "error");
    } finally {
      setActiveApproval(null);
      setDecisionType(null);
      setComment("");
    }
  }

  const TERMINAL_RUN_STATUSES = ["completed", "failed", "cancelled", "canceled"];

  const filtered =
    filter === "all" ? approvals : approvals.filter(
      (a) => a.status === "pending" && !TERMINAL_RUN_STATUSES.includes(a.run_status ?? "")
    );

  // Truly actionable: pending AND run is NOT in a terminal state
  const pendingCount = approvals.filter(
    (a) => a.status === "pending" && !TERMINAL_RUN_STATUSES.includes(a.run_status ?? "")
  ).length;
  // Stale: pending but run has reached a terminal state
  const staleCount = approvals.filter(
    (a) => a.status === "pending" && TERMINAL_RUN_STATUSES.includes(a.run_status ?? "")
  ).length;

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">Approvals</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">Review and action pending workflow approvals</p>
        </div>
        <div className="flex items-center gap-3">
          {pendingCount > 0 && (
            <span className="flex items-center gap-2 rounded-full bg-amber-100 dark:bg-amber-950/50 px-3 py-1.5 text-sm font-medium text-amber-700 dark:text-amber-400">
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-amber-500" />
              </span>
              {pendingCount} pending
            </span>
          )}
          {staleCount > 0 && (
            <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-3 py-1.5 text-sm font-medium text-gray-500 dark:text-gray-400" title="Pending approvals whose run is no longer waiting">
              {staleCount} stale
            </span>
          )}
          <span className="text-xs text-neutral-400">Live (SSE)</span>
        </div>
      </div>

      {/* Approver name + filter */}
      <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400 shrink-0">Your name:</label>
            <input value={approverName} onChange={(e) => saveApproverName(e.target.value)} placeholder="approver name"
              className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-1.5 text-sm text-neutral-900 dark:text-neutral-100 focus:border-blue-500 focus:outline-none w-48" />
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <button onClick={() => setFilter("pending")}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${filter === "pending" ? "bg-amber-100 dark:bg-amber-950/50 text-amber-700 dark:text-amber-400" : "text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"}`}>
              Actionable ({pendingCount})
            </button>
            <button onClick={() => setFilter("all")}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${filter === "all" ? "bg-blue-100 dark:bg-blue-950/50 text-blue-700 dark:text-blue-400" : "text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"}`}>
              All ({approvals.length})
            </button>
          </div>
        </div>
      </div>

      {/* Pending approvals */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 p-16 text-center text-neutral-400">
          <svg className="w-12 h-12 mx-auto mb-3 text-neutral-300 dark:text-neutral-700" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
          {filter === "pending" ? "No actionable approvals — all caught up!" : "No approvals found."}
        </div>
      ) : (
        <div className="space-y-4">
          {filtered.map((approval) => {
            const overdue = approval.status === "pending" && !!approval.expires_at && new Date(approval.expires_at) < new Date();
            const isPending = approval.status === "pending";
            return (
              <div key={approval.approval_id} className={`rounded-xl border p-5 shadow-sm transition-shadow hover:shadow-md ${overdue ? "border-red-300 bg-red-50 dark:bg-red-950/20" : isPending ? "border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/20" : "border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900"}`}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <ApprovalStatusBadge status={approval.status} />
                      {/* Run status badge: show stale warning when run has reached a terminal state */}
                      {approval.status === "pending" && TERMINAL_RUN_STATUSES.includes(approval.run_status ?? "") && (
                        <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-[10px] font-medium text-gray-500 dark:text-gray-400" title={`Run is ${approval.run_status}`}>
                          ⚠ stale (run: {approval.run_status})
                        </span>
                      )}
                      {approval.run_status === "waiting_approval" && approval.status === "pending" && (
                        <span className="rounded-full bg-amber-50 dark:bg-amber-950/30 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400" title="Run is actively waiting">
                          ▶ run waiting
                        </span>
                      )}
                      <span className="text-xs text-neutral-500 dark:text-neutral-400">Node: {approval.node_id}</span>
                      {approval.expires_at && approval.status === "pending" && (
                        <CountdownBadge expiresAt={approval.expires_at} />
                      )}
                      {overdue && (
                        <span className="rounded-full bg-red-100 dark:bg-red-950 px-2 py-0.5 text-[10px] font-semibold text-red-600 dark:text-red-400 animate-pulse">⚠ OVERDUE</span>
                      )}
                    </div>
                    <p className="mt-2 text-sm font-medium text-neutral-900 dark:text-neutral-100">{approval.prompt}</p>
                    <p className="mt-1 text-xs text-neutral-400">
                      Run:{" "}
                      <Link href={`/runs/${approval.run_id}`} className="text-blue-600 dark:text-blue-400 hover:underline">
                        {approval.run_id.slice(0, 8)}…
                      </Link>
                      {" · "}
                      {new Date(approval.created_at).toLocaleString()}
                    </p>
                    {approval.decided_by && (
                      <p className="mt-1 text-xs text-neutral-400">
                        Decided by: {approval.decided_by} {approval.decided_at ? `at ${new Date(approval.decided_at).toLocaleString()}` : ""}
                      </p>
                    )}
                  </div>
                  {approval.status === "pending" && (
                    <div className="flex shrink-0 gap-2">
                      <button onClick={() => { setActiveApproval(approval); setDecisionType("approved"); setComment(""); }}
                        className="flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 transition-colors">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                        Approve
                      </button>
                      <button onClick={() => { setActiveApproval(approval); setDecisionType("rejected"); setComment(""); }}
                        className="flex items-center gap-1.5 rounded-lg border border-red-300 dark:border-red-700 px-4 py-2 text-sm font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 transition-colors">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Decision Modal */}
      {activeApproval && decisionType && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-xl bg-white dark:bg-neutral-900 shadow-xl overflow-hidden">
            <div className={`p-4 border-b ${decisionType === "approved" ? "border-green-100 dark:border-green-900/30 bg-green-50 dark:bg-green-950/20" : "border-red-100 dark:border-red-900/30 bg-red-50 dark:bg-red-950/20"}`}>
              <h3 className={`text-lg font-semibold ${decisionType === "approved" ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}`}>
                {decisionType === "approved" ? "Approve" : "Reject"} Task
              </h3>
            </div>
            <div className="p-6 space-y-4">
              <div className="space-y-2">
                <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{activeApproval.prompt}</p>
                <div className="flex flex-wrap gap-4 text-xs mt-2">
                  <div>
                    <span className="text-neutral-500">Run ID: </span>
                    <span className="font-mono text-neutral-700 dark:text-neutral-300">{activeApproval.run_id.slice(0, 12)}…</span>
                  </div>
                  <div>
                    <span className="text-neutral-500">Node: </span>
                    <span className="font-mono text-neutral-700 dark:text-neutral-300">{activeApproval.node_id}</span>
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                  Optional Comment
                </label>
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Provide a reason for your decision..."
                  autoFocus
                  className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 transition-colors"
                  rows={3}
                />
              </div>
            </div>
            <div className="border-t border-neutral-100 dark:border-neutral-800 p-4 bg-neutral-50/50 dark:bg-neutral-800/50 flex justify-end gap-3">
              <button
                onClick={() => { setActiveApproval(null); setDecisionType(null); }}
                className="rounded-lg px-4 py-2 text-sm font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDecision(activeApproval.approval_id, decisionType)}
                className={`rounded-lg px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors ${decisionType === "approved"
                    ? "bg-green-600 hover:bg-green-700"
                    : "bg-red-600 hover:bg-red-700"
                  }`}
              >
                Confirm {decisionType === "approved" ? "Approval" : "Rejection"}
              </button>
            </div>
          </div>
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

