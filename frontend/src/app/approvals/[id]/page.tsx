"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getApproval, submitApprovalDecision } from "@/lib/api";
import { ApprovalStatusBadge } from "@/components/shared/ApprovalStatusBadge";
import { useToast } from "@/components/Toast";
import { getUser } from "@/lib/auth";
import type { Approval } from "@/lib/types";

export default function ApprovalDetailPage() {
  const params = useParams();
  const approvalId = params.id as string;
  const { toast } = useToast();

  const [approval, setApproval] = useState<Approval | null>(null);
  const [loading, setLoading] = useState(true);
  const [comment, setComment] = useState("");
  const [approverName, setApproverName] = useState(() => {
    const user = getUser();
    if (user?.identity) return user.identity;
    if (typeof window !== "undefined") return localStorage.getItem("approver_name") ?? "";
    return "";
  });

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

  if (loading) return <p className="p-6 text-neutral-500">Loading approval...</p>;
  if (!approval) return <p className="p-6 text-red-500">Approval not found</p>;

  const overdue = isOverdueApproval(approval);
  const commentText = getApprovalComment(approval);
  const contextEntries = Object.entries(approval.context_data ?? {});

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 px-6 py-6">
      <div className="mx-auto max-w-6xl space-y-6">
      <Link href="/approvals" className="text-sm font-medium text-sky-700 hover:text-sky-800 hover:underline">
        ← Approval reports
      </Link>

      <div className={`rounded-2xl border p-8 shadow-sm ${overdue ? "border-red-200 bg-red-50/70 dark:border-red-900/40 dark:bg-red-950/20" : "border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900"}`}>
        <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0 flex-1 space-y-5">
            <div className="flex flex-wrap items-center gap-3">
              <ApprovalStatusBadge status={approval.status} />
              <span className="rounded-full bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-600">{approval.decision_type.replace(/_/g, " ")}</span>
              <span className="rounded-full bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-600">ID {approval.approval_id.slice(0, 12)}...</span>
              {approval.expires_at && approval.status === "pending" && <CountdownBadge expiresAt={approval.expires_at} />}
              {overdue && <span className="rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-700">Overdue</span>}
            </div>

            <div>
              <h1 className="text-2xl font-semibold text-neutral-900">{approval.prompt}</h1>
              <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">
                Approval requested at node <span className="font-mono text-neutral-700">{approval.node_id}</span> for run{" "}
                <Link href={`/runs/${approval.run_id}`} className="text-sky-700 hover:text-sky-800 hover:underline">
                  {approval.run_id.slice(0, 12)}...
                </Link>
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-4">
              <MetricTile label="Requested" value={formatTimestamp(approval.created_at)} subvalue={formatDistance(approval.created_at)} />
              <MetricTile label={approval.status === "pending" ? "Waiting" : "Resolved"} value={approval.status === "pending" ? (approval.expires_at ? formatTimestamp(approval.expires_at) : "No expiry") : formatTimestamp(approval.decided_at)} subvalue={approval.status === "pending" ? "Awaiting a human decision" : getDecisionLatency(approval)} />
              <MetricTile label="Decided By" value={approval.decided_by ?? "-"} subvalue={approval.decided_at ? formatTimestamp(approval.decided_at) : "No decision yet"} />
              <MetricTile label="Options" value={approval.options?.length ? String(approval.options.length) : "-"} subvalue={approval.options?.join(", ") ?? "Default approve/reject path"} />
            </div>

            <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4 dark:border-neutral-800 dark:bg-neutral-950/40">
              <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Approval Flow</p>
              <div className="mt-3 grid gap-3 md:grid-cols-3">
                <FlowStep title="1. Requested" detail={formatTimestamp(approval.created_at)} supporting={`Node ${approval.node_id}`} tone="blue" />
                <FlowStep title="2. Waiting" detail={approval.status === "pending" ? (approval.expires_at ? `Until ${formatTimestamp(approval.expires_at)}` : "Open ended") : getDecisionLatency(approval)} supporting={approval.status === "pending" ? "Decision still required" : "Decision stored"} tone={overdue ? "red" : "amber"} />
                <FlowStep title="3. Outcome" detail={approval.status.replace(/_/g, " ")} supporting={approval.decided_at ? formatTimestamp(approval.decided_at) : "No outcome yet"} tone={approval.status === "approved" ? "emerald" : approval.status === "rejected" ? "red" : "neutral"} />
              </div>
            </div>
          </div>

          <div className="w-full shrink-0 xl:w-72">
            <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4 dark:border-neutral-800 dark:bg-neutral-950/40">
              <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Links</p>
              <div className="mt-3 space-y-3">
                <Link href={`/runs/${approval.run_id}`} className="block rounded-2xl border border-neutral-200 bg-white px-3 py-2 text-center text-sm font-medium text-sky-700 hover:bg-sky-50 dark:border-neutral-800 dark:bg-neutral-900 dark:text-sky-300 dark:hover:bg-sky-950/30">
                  Open run history
                </Link>
                <Link href="/approvals" className="block rounded-2xl border border-neutral-200 bg-white px-3 py-2 text-center text-sm font-medium text-neutral-700 hover:bg-neutral-100 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800">
                  Back to approval list
                </Link>
              </div>
            </div>
          </div>
        </div>

        {contextEntries.length > 0 && (
          <div className="mt-6 rounded-2xl border border-sky-100 bg-sky-50/70 p-5 dark:border-sky-900/40 dark:bg-sky-950/20">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-sky-700">Context Data</h3>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {contextEntries.map(([key, value]) => (
                <div key={key} className="rounded-2xl bg-white/80 p-3 dark:bg-neutral-900/80">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-sky-600">{key}</p>
                  <p className="mt-1 break-words text-sm text-neutral-700 dark:text-neutral-300">{compactValue(value)}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {(commentText || approval.decision_payload) && (
          <div className="mt-6 rounded-2xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Decision Report</h3>
            {commentText && <p className="mt-3 text-sm text-neutral-700 dark:text-neutral-300">{commentText}</p>}
            {approval.decision_payload && (
              <pre className="mt-3 max-h-72 overflow-auto rounded-2xl bg-neutral-50 p-3 font-mono text-xs text-neutral-600 dark:bg-neutral-950/40 dark:text-neutral-300">
                {JSON.stringify(approval.decision_payload, null, 2)}
              </pre>
            )}
          </div>
        )}

        {approval.status === "pending" && (
          <div className="mt-8 space-y-4 border-t border-neutral-200 pt-6 dark:border-neutral-800">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="mb-2 block text-sm font-medium text-neutral-700 dark:text-neutral-300">Approver name</label>
                <input
                  value={approverName}
                  onChange={(e) => saveApproverName(e.target.value)}
                  placeholder="approver name"
                  className="w-full rounded-2xl border border-neutral-200 bg-white px-3 py-2.5 text-sm focus:border-sky-400 focus:outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-neutral-700 dark:text-neutral-300">Decision note</label>
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="This note will be stored in the approval report"
                  className="w-full rounded-2xl border border-neutral-200 bg-white p-3 text-sm focus:border-sky-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
                  rows={3}
                />
              </div>
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => handleDecision("approved")}
                className="flex-1 rounded-full bg-green-600 py-2.5 text-sm font-medium text-white hover:bg-green-700"
              >
                Approve
              </button>
              <button
                onClick={() => handleDecision("rejected")}
                className="flex-1 rounded-full border border-red-300 py-2.5 text-sm font-medium text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/30"
              >
                Reject
              </button>
            </div>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}

function isOverdueApproval(approval: Approval): boolean {
  return approval.status === "pending" && !!approval.expires_at && new Date(approval.expires_at).getTime() < Date.now();
}

function getApprovalComment(approval: Approval): string | null {
  if (approval.comment && approval.comment.trim()) return approval.comment.trim();
  const raw = approval.decision_payload?.comment;
  return typeof raw === "string" && raw.trim() ? raw.trim() : null;
}

function getDecisionLatency(approval: Approval): string {
  if (!approval.decided_at) return "No decision time recorded";
  const created = new Date(approval.created_at).getTime();
  const decided = new Date(approval.decided_at).getTime();
  const diffMinutes = Math.max(0, decided - created) / 60000;
  if (diffMinutes < 1) return `${Math.round(diffMinutes * 60)} sec response`;
  if (diffMinutes < 60) return `${diffMinutes.toFixed(1)} min response`;
  return `${(diffMinutes / 60).toFixed(1)} hr response`;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function formatDistance(from: string | null | undefined, to?: string | null | undefined): string {
  if (!from) return "-";
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Date.now();
  const diffMinutes = Math.max(0, end - start) / 60000;
  if (diffMinutes < 1) return `${Math.round(diffMinutes * 60)} sec`;
  if (diffMinutes < 60) return `${diffMinutes.toFixed(1)} min`;
  if (diffMinutes < 1440) return `${(diffMinutes / 60).toFixed(1)} hr`;
  return `${(diffMinutes / 1440).toFixed(1)} d`;
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

function MetricTile({ label, value, subvalue }: { label: string; value: string; subvalue: string }) {
  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">{label}</p>
      <p className="mt-2 text-sm font-medium text-neutral-900 dark:text-neutral-100">{value}</p>
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
    blue: "border-blue-200 bg-blue-50",
    amber: "border-amber-200 bg-amber-50",
    red: "border-red-200 bg-red-50",
    emerald: "border-emerald-200 bg-emerald-50",
    neutral: "border-neutral-200 bg-neutral-50",
  };
  return (
    <div className={`rounded-2xl border p-4 ${tones[tone]}`}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">{title}</p>
      <p className="mt-2 text-sm font-medium text-neutral-900 dark:text-neutral-100">{detail}</p>
      <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{supporting}</p>
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
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${isUrgent ? "bg-red-100 text-red-600 animate-pulse" : "bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400"}`}>
      ⏱ {remaining}
    </span>
  );
}

