"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listApprovals, submitApprovalDecision } from "@/lib/api";
import { subscribeToApprovalUpdates } from "@/lib/sse";
import { ApprovalStatusBadge } from "@/components/shared/ApprovalStatusBadge";
import { useToast } from "@/components/Toast";
import { getUser } from "@/lib/auth";
import type { Approval } from "@/lib/types";

const TERMINAL_RUN_STATUSES = ["completed", "failed", "cancelled", "canceled"];

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "pending" | "resolved">("pending");
  const [activeApproval, setActiveApproval] = useState<Approval | null>(null);
  const [decisionType, setDecisionType] = useState<"approved" | "rejected" | null>(null);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [approverName, setApproverName] = useState(() => {
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
    const cleanup = subscribeToApprovalUpdates(
      () => {
        loadApprovals();
      },
      () => {
        console.warn("Approval SSE disconnected, falling back to polling");
      }
    );
    return cleanup;
  }, []);

  function saveApproverName(name: string) {
    setApproverName(name);
    if (typeof window !== "undefined") localStorage.setItem("approver_name", name);
  }

  async function handleDecision(approvalId: string, decision: string) {
    try {
      await submitApprovalDecision(approvalId, decision, approverName.trim() || "ui_user", comment || undefined);
      toast(`Decision submitted: ${decision}`, "success");
      await loadApprovals();
    } catch (err) {
      console.error(err);
      toast("Decision failed", "error");
    } finally {
      setActiveApproval(null);
      setDecisionType(null);
      setSelectedOption(null);
      setComment("");
    }
  }

  const actionableApprovals = approvals.filter(isActionableApproval);
  const staleApprovals = approvals.filter((approval) => approval.status === "pending" && isTerminalRunStatus(approval.run_status));
  const overdueApprovals = approvals.filter(isOverdueApproval);
  const resolvedApprovals = approvals.filter((approval) => approval.status !== "pending");
  const approvedCount = resolvedApprovals.filter((approval) => approval.status === "approved").length;
  const rejectedCount = resolvedApprovals.filter((approval) => approval.status === "rejected").length;
  const avgDecisionMinutes = getAverageDecisionMinutes(resolvedApprovals);

  const filtered = approvals.filter((approval) => {
    if (filter === "pending") return isActionableApproval(approval);
    if (filter === "resolved") return approval.status !== "pending";
    return true;
  });

  return (
    <div className="min-h-[calc(100vh-4rem)] space-y-6 bg-neutral-50 p-6">
      <div>
        <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Approvals</h1>
        <p className="mt-0.5 text-sm text-neutral-500 dark:text-neutral-400">Human-in-the-loop approval requests</p>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-neutral-200 bg-white px-4 py-2.5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <label className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Your name</label>
        <input
          value={approverName}
          onChange={(e) => saveApproverName(e.target.value)}
          placeholder="Used when recording decisions"
          className="w-48 rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-sm text-neutral-900 focus:border-blue-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100"
        />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : (
        <>
          {/* Pending Approvals */}
          <section>
            <div className="mb-3 flex items-center gap-2">
              <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">Pending Approvals</h2>
              {actionableApprovals.length > 0 && (
                <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                  {actionableApprovals.length}
                </span>
              )}
            </div>
            {actionableApprovals.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-neutral-200 bg-white p-10 text-center text-sm text-neutral-400 dark:border-neutral-700 dark:bg-neutral-900">
                No pending approvals — all clear.
              </div>
            ) : (
              <div className="space-y-3">
                {actionableApprovals.map((approval) => {
                  const contextEntries = Object.entries(approval.context_data ?? {}).slice(0, 6);
                  return (
                    <div key={approval.approval_id}
                      className="rounded-2xl border border-amber-200 bg-amber-50/80 p-5 shadow-sm dark:border-amber-900/40 dark:bg-amber-950/20">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
                              {formatNodeTitle(approval.node_id)}
                            </h3>
                            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">Pending</span>
                          </div>
                          <p className="mt-1 text-sm text-neutral-700 dark:text-neutral-300">{approval.prompt}</p>
                          {contextEntries.length > 0 && (
                            <pre className="mt-3 max-h-36 overflow-auto rounded-lg border border-amber-100 bg-white/70 p-3 text-xs text-neutral-600 dark:border-amber-900/30 dark:bg-neutral-900/60 dark:text-neutral-300">
                              {JSON.stringify(Object.fromEntries(contextEntries), null, 2)}
                            </pre>
                          )}
                          <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
                            Requested {formatDistance(approval.created_at)} ago
                            {approval.expires_at && (
                              <span className="ml-1.5 text-amber-600 dark:text-amber-400">· due {formatTimestamp(approval.expires_at)}</span>
                            )}
                          </p>
                        </div>
                        <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
                          <Link href={`/runs/${approval.run_id}`}
                            className="rounded-full border border-neutral-200 bg-white px-4 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300">
                            View Run
                          </Link>
                          <button
                            onClick={() => { setActiveApproval(approval); setDecisionType("approved"); setSelectedOption(null); setComment(""); }}
                            className="rounded-full bg-neutral-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-200">
                            Review
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* Recent History */}
          {resolvedApprovals.length > 0 && (
            <section>
              <h2 className="mb-3 text-base font-semibold text-neutral-900 dark:text-neutral-100">Recent History</h2>
              <div className="overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
                  {resolvedApprovals.slice(0, 20).map((approval) => {
                    const commentText = getApprovalComment(approval);
                    const isApproved = approval.status === "approved";
                    return (
                      <div key={approval.approval_id} className="flex items-start gap-4 px-5 py-4">
                        <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${isApproved ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-400" : "bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-400"}`}>
                          {isApproved ? (
                            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7"/></svg>
                          ) : (
                            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{formatNodeTitle(approval.node_id)}</span>
                            <ApprovalStatusBadge status={approval.status} />
                          </div>
                          <p className="mt-0.5 line-clamp-1 text-xs text-neutral-500 dark:text-neutral-400">{approval.prompt}</p>
                          <p className="mt-0.5 text-[11px] text-neutral-400 dark:text-neutral-500">
                            {approval.decided_by && <span>decided by {approval.decided_by} · </span>}
                            {formatTimestamp(approval.decided_at)}
                            {commentText && <span> · &ldquo;{commentText}&rdquo;</span>}
                          </p>
                        </div>
                        <Link href={`/runs/${approval.run_id}`}
                          className="shrink-0 text-xs font-medium text-sky-600 hover:underline dark:text-sky-400">
                          View Run
                        </Link>
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
          )}
        </>
      )}

      {activeApproval && decisionType && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
          <div className="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-xl dark:bg-neutral-900">
            <div className={`border-b p-5 ${decisionType === "approved" ? "border-green-100 bg-green-50 dark:border-green-900/30 dark:bg-green-950/20" : "border-red-100 bg-red-50 dark:border-red-900/30 dark:bg-red-950/20"}`}>
              <h3 className={`text-lg font-semibold ${decisionType === "approved" ? "text-green-700 dark:text-green-300" : "text-red-700 dark:text-red-300"}`}>
                {decisionType === "approved" ? "Approve workflow step" : "Reject workflow step"}
              </h3>
              <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-300">This decision will be stored in the approval report and reflected in the run history.</p>
            </div>
            <div className="space-y-5 p-6">
              <div>
                <p className="whitespace-pre-wrap text-base font-medium text-neutral-900 dark:text-neutral-100">{activeApproval.prompt}</p>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-neutral-500 dark:text-neutral-400">
                  <span className="rounded-full bg-neutral-100 px-2.5 py-1 dark:bg-neutral-800">Run {activeApproval.run_id.slice(0, 12)}...</span>
                  <span className="rounded-full bg-neutral-100 px-2.5 py-1 font-mono dark:bg-neutral-800">Node {activeApproval.node_id}</span>
                  {activeApproval.expires_at && <span className="rounded-full bg-amber-50 px-2.5 py-1 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">Due {formatTimestamp(activeApproval.expires_at)}</span>}
                </div>
              </div>

              {Object.keys(activeApproval.context_data ?? {}).length > 0 && (
                <div className="rounded-2xl border border-sky-100 bg-sky-50/70 p-4 dark:border-sky-900/40 dark:bg-sky-950/20">
                  <p className="text-xs font-semibold uppercase tracking-wide text-sky-700 dark:text-sky-300">Decision context</p>
                  <pre className="mt-3 max-h-52 overflow-auto rounded-lg bg-white/80 p-3 text-xs text-neutral-700 dark:bg-neutral-900/70 dark:text-neutral-200">{JSON.stringify(activeApproval.context_data, null, 2)}</pre>
                </div>
              )}

              {activeApproval.options?.length ? (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">Available options</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {activeApproval.options.map((option) => (
                      <button
                        key={option}
                        onClick={() => setSelectedOption(option)}
                        className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                          selectedOption === option
                            ? "border-blue-500 bg-blue-600 text-white"
                            : "border-neutral-200 bg-neutral-50 text-neutral-700 hover:border-blue-300 hover:bg-blue-50 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-200 dark:hover:border-blue-600 dark:hover:bg-blue-950/30"
                        }`}
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                  {!selectedOption && (
                    <p className="mt-1.5 text-xs text-amber-600 dark:text-amber-400">Select an option above before confirming.</p>
                  )}
                </div>
              ) : null}

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-sm font-medium text-neutral-700 dark:text-neutral-300">Approver name</label>
                  <input
                    value={approverName}
                    onChange={(e) => saveApproverName(e.target.value)}
                    placeholder="approver name"
                    className="w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100"
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-neutral-700 dark:text-neutral-300">Decision summary</label>
                  <div className={`rounded-lg border px-3 py-2 text-sm font-medium ${
                    selectedOption
                      ? "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/40 dark:bg-blue-950/20 dark:text-blue-300"
                      : decisionType === "approved"
                      ? "border-green-200 bg-green-50 text-green-700 dark:border-green-900/40 dark:bg-green-950/20 dark:text-green-300"
                      : "border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-300"
                  }`}>
                    {selectedOption
                      ? `Decision: "${selectedOption}" — run will resume on this route.`
                      : decisionType === "approved"
                      ? "The run will resume on approval."
                      : "The run will resume on rejection handling."}
                  </div>
                </div>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-neutral-700 dark:text-neutral-300">Decision note</label>
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Why are you making this decision? This will be stored in the approval report."
                  autoFocus
                  rows={4}
                  className="w-full rounded-lg border border-neutral-300 bg-white p-3 text-sm focus:border-blue-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 border-t border-neutral-100 bg-neutral-50/80 p-4 dark:border-neutral-800 dark:bg-neutral-950/70">
              <button
                onClick={() => {
                  setActiveApproval(null);
                  setDecisionType(null);
                  setSelectedOption(null);
                }}
                className="rounded-lg px-4 py-2 text-sm font-medium text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  const decision = activeApproval.options?.length
                    ? (selectedOption ?? decisionType ?? "approved")
                    : (decisionType ?? "approved");
                  handleDecision(activeApproval.approval_id, decision);
                }}
                disabled={!!(activeApproval.options?.length && !selectedOption)}
                className={`rounded-lg px-4 py-2 text-sm font-medium text-white ${
                  activeApproval.options?.length && !selectedOption
                    ? "cursor-not-allowed bg-neutral-400"
                    : decisionType === "approved"
                    ? "bg-green-600 hover:bg-green-700"
                    : "bg-red-600 hover:bg-red-700"
                }`}
              >
                Confirm {decisionType === "approved" ? "approval" : "rejection"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function formatNodeTitle(nodeId: string): string {
  return nodeId.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function isTerminalRunStatus(runStatus: string | null | undefined): boolean {
  return !!runStatus && TERMINAL_RUN_STATUSES.includes(runStatus);
}

function isActionableApproval(approval: Approval): boolean {
  return approval.status === "pending" && !isTerminalRunStatus(approval.run_status);
}

function isOverdueApproval(approval: Approval): boolean {
  return approval.status === "pending" && !!approval.expires_at && new Date(approval.expires_at).getTime() < Date.now();
}

function getApprovalComment(approval: Approval): string | null {
  if (approval.comment && approval.comment.trim()) return approval.comment.trim();
  const raw = approval.decision_payload?.comment;
  return typeof raw === "string" && raw.trim() ? raw.trim() : null;
}

function getAverageDecisionMinutes(approvals: Approval[]): number | null {
  const durations = approvals
    .map((approval) => getDecisionLatencyMinutes(approval))
    .filter((value): value is number => value != null);
  if (!durations.length) return null;
  return durations.reduce((sum, value) => sum + value, 0) / durations.length;
}

function getDecisionLatencyMinutes(approval: Approval): number | null {
  if (!approval.decided_at) return null;
  const created = new Date(approval.created_at).getTime();
  const decided = new Date(approval.decided_at).getTime();
  if (!Number.isFinite(created) || !Number.isFinite(decided) || decided < created) return null;
  return (decided - created) / 60000;
}

function getDecisionLatency(approval: Approval): string {
  const minutes = getDecisionLatencyMinutes(approval);
  if (minutes == null) return "No decision time recorded";
  if (minutes < 1) return `${Math.round(minutes * 60)} sec response`;
  if (minutes < 60) return `${minutes.toFixed(1)} min response`;
  const hours = minutes / 60;
  return `${hours.toFixed(1)} hr response`;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function formatDistance(from: string | null | undefined, to?: string | null | undefined): string {
  if (!from) return "-";
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "-";
  const diffMs = Math.max(0, end - start);
  const diffMinutes = diffMs / 60000;
  if (diffMinutes < 1) return `${Math.round(diffMs / 1000)} sec`;
  if (diffMinutes < 60) return `${diffMinutes.toFixed(1)} min`;
  const diffHours = diffMinutes / 60;
  if (diffHours < 24) return `${diffHours.toFixed(1)} hr`;
  return `${(diffHours / 24).toFixed(1)} d`;
}

function compactValue(value: unknown): string {
  if (value == null) return "-";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function StatCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "amber" | "red" | "emerald" | "blue";
}) {
  const tones: Record<string, string> = {
    amber: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-300",
    red: "border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-300",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-300",
    blue: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/40 dark:bg-blue-950/20 dark:text-blue-300",
  };
  return (
    <div className={`rounded-2xl border p-4 shadow-sm ${tones[tone]}`}>
      <p className="text-xs font-semibold uppercase tracking-wide">{label}</p>
      <p className="mt-1.5 text-2xl font-bold">{value}</p>
      <p className="mt-1.5 text-xs opacity-80">{detail}</p>
    </div>
  );
}

function FilterButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${active ? "bg-blue-600 text-white" : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-700"}`}
    >
      {label}
    </button>
  );
}

function FlowTag({ label, tone }: { label: string; tone: "violet" | "emerald" | "amber" | "red" | "blue" | "neutral" }) {
  const tones: Record<string, string> = {
    violet: "bg-violet-50 text-violet-700 dark:bg-violet-950/30 dark:text-violet-300",
    emerald: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300",
    amber: "bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300",
    red: "bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300",
    blue: "bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-300",
    neutral: "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
  };
  return <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${tones[tone]}`}>{label}</span>;
}

function MetricTile({ label, value, subvalue }: { label: string; value: string; subvalue: string }) {
  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-3 dark:border-neutral-800 dark:bg-neutral-900">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">{label}</p>
      <p className="mt-1.5 text-sm font-medium text-neutral-900 dark:text-neutral-100">{value}</p>
      <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{subvalue}</p>
    </div>
  );
}

function FlowStep({
  title,
  detail,
  supporting,
  tone,
}: {
  title: string;
  detail: string;
  supporting: string;
  tone: "blue" | "amber" | "red" | "emerald" | "neutral";
}) {
  const tones: Record<string, string> = {
    blue: "border-blue-200 bg-blue-50 dark:border-blue-900/40 dark:bg-blue-950/20",
    amber: "border-amber-200 bg-amber-50 dark:border-amber-900/40 dark:bg-amber-950/20",
    red: "border-red-200 bg-red-50 dark:border-red-900/40 dark:bg-red-950/20",
    emerald: "border-emerald-200 bg-emerald-50 dark:border-emerald-900/40 dark:bg-emerald-950/20",
    neutral: "border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900",
  };
  return (
    <div className={`rounded-2xl border p-3 ${tones[tone]}`}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">{title}</p>
      <p className="mt-1.5 text-sm font-medium text-neutral-900 dark:text-neutral-100">{detail}</p>
      <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{supporting}</p>
    </div>
  );
}

