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

  async function handleDecision(approvalId: string, decision: "approved" | "rejected") {
    try {
      await submitApprovalDecision(approvalId, decision, approverName.trim() || "ui_user", comment || undefined);
      toast(`Approval ${decision}`, "success");
      await loadApprovals();
    } catch (err) {
      console.error(err);
      toast("Decision failed", "error");
    } finally {
      setActiveApproval(null);
      setDecisionType(null);
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
    <div className="min-h-[calc(100vh-4rem)] space-y-4 bg-neutral-50 p-6">
      <section className="rounded-2xl border border-neutral-200 bg-white px-6 py-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-neutral-400">Approvals Workspace</p>
            <h1 className="mt-1 text-3xl font-bold text-neutral-900 dark:text-neutral-100">Approval Reports</h1>
            <p className="mt-1 max-w-3xl text-sm text-neutral-500 dark:text-neutral-400">
              Review active approvals, decision latency, stale waits, and the full approval flow per run.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
            <span className="rounded-full bg-emerald-50 px-3 py-1.5 font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
              Live approval stream
            </span>
            {staleApprovals.length > 0 && (
              <span className="rounded-full bg-neutral-100 px-3 py-1.5 font-medium text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                {staleApprovals.length} stale waiting records
              </span>
            )}
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Actionable" value={String(actionableApprovals.length)} detail="Pending approvals on active runs" tone="amber" />
          <StatCard label="Overdue" value={String(overdueApprovals.length)} detail="Pending beyond their expiry window" tone="red" />
          <StatCard label="Resolved" value={`${approvedCount}/${rejectedCount}`} detail="Approved / rejected decisions" tone="emerald" />
          <StatCard label="Avg Response" value={avgDecisionMinutes != null ? `${avgDecisionMinutes.toFixed(1)} min` : "-"} detail="Mean time from request to decision" tone="blue" />
        </div>
      </section>

      <div className="rounded-2xl border border-neutral-200 bg-white p-3 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-xs font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-400">Approver</label>
            <input
              value={approverName}
              onChange={(e) => saveApproverName(e.target.value)}
              placeholder="name used for decisions"
              className="w-52 rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-sm text-neutral-900 focus:border-blue-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100"
            />
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-neutral-500 dark:text-neutral-400">
              <span className="rounded-full border px-2 py-1">Pending {actionableApprovals.length}</span>
              <span className="rounded-full border px-2 py-1">Resolved {resolvedApprovals.length}</span>
              <span className="rounded-full border px-2 py-1">Stale {staleApprovals.length}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
            <FilterButton label={`Pending (${actionableApprovals.length})`} active={filter === "pending"} onClick={() => setFilter("pending")} />
            <FilterButton label={`Resolved (${resolvedApprovals.length})`} active={filter === "resolved"} onClick={() => setFilter("resolved")} />
            <FilterButton label={`All (${approvals.length})`} active={filter === "all"} onClick={() => setFilter("all")} />
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-neutral-300 p-16 text-center text-sm text-neutral-400 dark:border-neutral-700">
          {filter === "pending" ? "No actionable approvals remain." : filter === "resolved" ? "No resolved approvals yet." : "No approvals found."}
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((approval) => {
            const overdue = isOverdueApproval(approval);
            const actionable = isActionableApproval(approval);
            const commentText = getApprovalComment(approval);
            const contextEntries = Object.entries(approval.context_data ?? {}).slice(0, 4);
            const runTerminal = isTerminalRunStatus(approval.run_status);
            return (
              <article
                key={approval.approval_id}
                className={`rounded-2xl border p-4 shadow-sm transition-shadow hover:shadow-md ${overdue
                  ? "border-red-200 bg-red-50/80 dark:border-red-900/40 dark:bg-red-950/20"
                  : actionable
                    ? "border-amber-200 bg-amber-50/70 dark:border-amber-900/40 dark:bg-amber-950/20"
                    : "border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900"}`}
              >
                <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_240px] xl:items-start">
                  <div className="min-w-0 space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <ApprovalStatusBadge status={approval.status} />
                      <FlowTag label={approval.decision_type.replace(/_/g, " ")} tone="violet" />
                      {approval.run_status && (
                        <FlowTag label={`Run ${approval.run_status.replace(/_/g, " ")}`} tone={runTerminal ? "neutral" : approval.run_status === "waiting_approval" ? "amber" : "blue"} />
                      )}
                      {overdue && <FlowTag label="Overdue" tone="red" />}
                      {approval.options?.length ? <FlowTag label={`${approval.options.length} option${approval.options.length === 1 ? "" : "s"}`} tone="emerald" /> : null}
                      {contextEntries.length ? <FlowTag label={`${contextEntries.length} context fields`} tone="blue" /> : null}
                    </div>

                    <div>
                      <p className="text-base font-semibold text-neutral-900 dark:text-neutral-100">{approval.prompt}</p>
                      <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                        Requested {formatTimestamp(approval.created_at)} on node <span className="font-mono">{approval.node_id}</span>
                      </p>
                    </div>

                    <div className="grid gap-2 md:grid-cols-3">
                      <MetricTile label="Requested" value={formatTimestamp(approval.created_at)} subvalue={formatDistance(approval.created_at)} />
                      <MetricTile
                        label={approval.status === "pending" ? "Waiting" : "Resolved"}
                        value={approval.status === "pending" ? (approval.expires_at ? `Due ${formatTimestamp(approval.expires_at)}` : "No expiry") : formatTimestamp(approval.decided_at)}
                        subvalue={approval.status === "pending" ? (approval.expires_at ? formatDistance(approval.created_at, approval.expires_at) : "Awaiting a human decision") : getDecisionLatency(approval)}
                      />
                      <MetricTile
                        label="Run"
                        value={approval.run_status ? approval.run_status.replace(/_/g, " ") : "Unknown"}
                        subvalue={runTerminal ? "Run already finished" : approval.status === "pending" ? "Decision can still resume execution" : "Decision already applied"}
                      />
                    </div>

                    <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-950/40">
                      <div className="flex flex-wrap items-center gap-2 text-xs font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
                        <span>Approval Flow</span>
                        {approval.decided_by && <span className="normal-case tracking-normal">by {approval.decided_by}</span>}
                      </div>
                      <div className="mt-3 grid gap-2 md:grid-cols-3">
                        <FlowStep title="1. Requested" tone="blue" detail={formatTimestamp(approval.created_at)} supporting={`Run ${approval.run_id.slice(0, 12)}...`} />
                        <FlowStep
                          title="2. Waiting"
                          tone={overdue ? "red" : "amber"}
                          detail={approval.status === "pending" ? (approval.expires_at ? `Until ${formatTimestamp(approval.expires_at)}` : "Open-ended") : getDecisionLatency(approval)}
                          supporting={runTerminal && approval.status === "pending" ? "Run is terminal; this record is stale" : approval.status === "pending" ? "Still waiting on approval" : "Decision received"}
                        />
                        <FlowStep
                          title="3. Outcome"
                          tone={approval.status === "approved" ? "emerald" : approval.status === "rejected" ? "red" : "neutral"}
                          detail={approval.status === "pending" ? "Pending" : approval.status.replace(/_/g, " ")}
                          supporting={approval.decided_at ? formatTimestamp(approval.decided_at) : "No decision yet"}
                        />
                      </div>
                    </div>

                    {contextEntries.length > 0 && (
                      <div className="rounded-2xl border border-sky-100 bg-sky-50/70 p-3 dark:border-sky-900/40 dark:bg-sky-950/20">
                        <p className="text-xs font-semibold uppercase tracking-wide text-sky-700 dark:text-sky-300">Context Snapshot</p>
                        <div className="mt-3 grid gap-2 md:grid-cols-2">
                          {contextEntries.map(([key, value]) => (
                            <div key={key} className="rounded-lg bg-white/80 p-2.5 dark:bg-neutral-900/60">
                              <p className="text-[11px] font-medium uppercase tracking-wide text-sky-600 dark:text-sky-400">{key}</p>
                              <p className="mt-1 break-words text-sm text-neutral-700 dark:text-neutral-200">{compactValue(value)}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {(commentText || approval.decision_payload) && (
                      <div className="rounded-2xl border border-neutral-200 bg-white p-3 dark:border-neutral-800 dark:bg-neutral-950/60">
                        <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">Decision Record</p>
                        {commentText && <p className="mt-2 text-sm text-neutral-700 dark:text-neutral-200">{commentText}</p>}
                        {approval.decision_payload && (
                          <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-neutral-50 p-3 text-xs text-neutral-600 dark:bg-neutral-900 dark:text-neutral-300">{JSON.stringify(approval.decision_payload, null, 2)}</pre>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="w-full shrink-0">
                    <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-950/50">
                      <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">Actions</p>
                      <div className="mt-3 space-y-2 text-sm">
                        <Link href={`/approvals/${approval.approval_id}`} className="block rounded-lg border border-neutral-200 bg-white px-3 py-2 text-center font-medium text-blue-600 hover:bg-blue-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-blue-300 dark:hover:bg-blue-950/30">
                          Open detail report
                        </Link>
                        <Link href={`/runs/${approval.run_id}`} className="block rounded-lg border border-neutral-200 bg-white px-3 py-2 text-center font-medium text-neutral-700 hover:bg-neutral-100 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-200 dark:hover:bg-neutral-800">
                          Open run history
                        </Link>
                        {approval.status === "pending" && (
                          <>
                            <button
                              onClick={() => {
                                setActiveApproval(approval);
                                setDecisionType("approved");
                                setComment("");
                              }}
                              className="w-full rounded-lg bg-green-600 px-4 py-2 font-medium text-white hover:bg-green-700"
                            >
                              Approve
                            </button>
                            <button
                              onClick={() => {
                                setActiveApproval(approval);
                                setDecisionType("rejected");
                                setComment("");
                              }}
                              className="w-full rounded-lg border border-red-300 px-4 py-2 font-medium text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/30"
                            >
                              Reject
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
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
                <p className="text-base font-medium text-neutral-900 dark:text-neutral-100">{activeApproval.prompt}</p>
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
                      <span key={option} className="rounded-full border border-neutral-200 bg-neutral-50 px-3 py-1 text-xs font-medium text-neutral-700 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-200">
                        {option}
                      </span>
                    ))}
                  </div>
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
                  <div className={`rounded-lg border px-3 py-2 text-sm font-medium ${decisionType === "approved" ? "border-green-200 bg-green-50 text-green-700 dark:border-green-900/40 dark:bg-green-950/20 dark:text-green-300" : "border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-300"}`}>
                    {decisionType === "approved" ? "The run will resume on approval." : "The run will resume on rejection handling."}
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
                }}
                className="rounded-lg px-4 py-2 text-sm font-medium text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDecision(activeApproval.approval_id, decisionType)}
                className={`rounded-lg px-4 py-2 text-sm font-medium text-white ${decisionType === "approved" ? "bg-green-600 hover:bg-green-700" : "bg-red-600 hover:bg-red-700"}`}
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

