"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { createRun, deleteProcedure, getGraph, getProcedure, listVersions, updateProcedure, explainProcedure, listRuns, getTrigger, upsertTrigger, deleteTrigger, fireTrigger, promoteProcedure, rollbackProcedure, getCase, isNotFoundError } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { ProcedureDetail, Procedure, ExplainReport, Run, TriggerRegistration } from "@/lib/types";
import { ProcedureStatusBadge as StatusBadge } from "@/components/shared/ProcedureStatusBadge";
import { isFieldSensitive } from "@/lib/redact";

const RELEASE_CHANNELS = ["dev", "qa", "prod"] as const;
type ReleaseChannel = (typeof RELEASE_CHANNELS)[number];

type ReleaseReadinessState = {
  status: "idle" | "checking" | "ready" | "blocked";
  issues: string[];
  checkedVersion: string | null;
};

function getNextReleaseChannel(channel: string | null | undefined): ReleaseChannel | null {
  const normalized = (channel ?? "dev") as ReleaseChannel;
  if (normalized === "dev") return "qa";
  if (normalized === "qa") return "prod";
  return null;
}

function releaseChannelBadgeClass(channel: string | null | undefined): string {
  const normalized = (channel ?? "dev").toLowerCase();
  if (normalized === "prod") return "bg-emerald-100 text-emerald-700 border-emerald-200";
  if (normalized === "qa") return "bg-amber-100 text-amber-700 border-amber-200";
  return "bg-sky-100 text-sky-700 border-sky-200";
}

/* ── Simple line-level diff helper ─────────────────────────── */
interface DiffHunk {
  type: "equal" | "added" | "removed";
  lineA?: number;
  lineB?: number;
  text: string;
}

function computeLineDiff(a: string, b: string): DiffHunk[] {
  const linesA = a.split("\n");
  const linesB = b.split("\n");
  const hunks: DiffHunk[] = [];

  // Simple LCS-based diff
  const m = linesA.length;
  const n = linesB.length;
  // Build LCS table
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] = linesA[i - 1] === linesB[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }
  // Backtrack to produce diff
  let i = m, j = n;
  const result: DiffHunk[] = [];
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && linesA[i - 1] === linesB[j - 1]) {
      result.push({ type: "equal", lineA: i, lineB: j, text: linesA[i - 1] });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.push({ type: "added", lineB: j, text: linesB[j - 1] });
      j--;
    } else {
      result.push({ type: "removed", lineA: i, text: linesA[i - 1] });
      i--;
    }
  }
  result.reverse();
  return result;
}

const WorkflowGraph = dynamic(
  () => import("@/components/WorkflowGraphWrapper"),
  { ssr: false, loading: () => <p className="text-sm text-neutral-400">Loading graph...</p> }
);

export default function ProcedureVersionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const procedureId = params.id as string;
  const version = params.version as string;

  const [procedure, setProcedure] = useState<ProcedureDetail | null>(null);
  const [versions, setVersions] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"overview" | "graph" | "ckp" | "versions" | "explain" | "runs" | "trigger">(
    () => {
      const t = searchParams.get("tab");
      return (t === "graph" || t === "ckp" || t === "versions" || t === "explain" || t === "runs" || t === "trigger") ? t : "overview";
    }
  );
  const [editMode, setEditMode] = useState(false);
  const [explainResult, setExplainResult] = useState<ExplainReport | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainError, setExplainError] = useState<string | null>(null);
  const [ckpText, setCkpText] = useState("");
  const [graphData, setGraphData] = useState<{ nodes: any[]; edges: any[] } | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState("");
  const [procedureRuns, setProcedureRuns] = useState<Run[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  const NODE_TYPE_BADGE_CLASS: Record<string, string> = {
    sequence: "bg-blue-500",
    processing: "bg-blue-600",
    transform: "bg-blue-700",
    subflow: "bg-blue-400",
    llm_action: "bg-violet-600",
    loop: "bg-orange-500",
    parallel: "bg-orange-600",
    logic: "bg-amber-500",
    verification: "bg-amber-600",
    human_approval: "bg-red-500",
    terminate: "bg-neutral-500",
  };

  // Trigger state
  const [triggerReg, setTriggerReg] = useState<TriggerRegistration | null>(null);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [triggerFetched, setTriggerFetched] = useState(false);
  const [triggerSaving, setTriggerSaving] = useState(false);
  const [triggerFiring, setTriggerFiring] = useState(false);
  const [triggerForm, setTriggerForm] = useState({
    trigger_type: "webhook" as string,
    schedule: "",
    webhook_secret: "",
    event_source: "",
    dedupe_window_seconds: 0,
    max_concurrent_runs: "",
    enabled: true,
  });
  const [showVarsModal, setShowVarsModal] = useState(false);
  const [varsForm, setVarsForm] = useState<Record<string, string>>({});
  const [varsErrors, setVarsErrors] = useState<Record<string, string>>({});
  const [runCreating, setRunCreating] = useState(false);
  const [runCaseId, setRunCaseId] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [diffVersionA, setDiffVersionA] = useState<string>("");
  const [diffVersionB, setDiffVersionB] = useState<string>("");
  const [diffResult, setDiffResult] = useState<{ left: string; right: string; hunks: DiffHunk[] } | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [promotingTo, setPromotingTo] = useState<ReleaseChannel | null>(null);
  const [rollingBack, setRollingBack] = useState(false);
  const [showRollbackModal, setShowRollbackModal] = useState(false);
  const [rollbackTargetVersion, setRollbackTargetVersion] = useState("");
  const [releaseReadiness, setReleaseReadiness] = useState<ReleaseReadinessState>({
    status: "idle",
    issues: [],
    checkedVersion: null,
  });
  const { toast } = useToast();

  useEffect(() => {
    const t = searchParams.get("tab");
    if (t === "builder" || t === "builder-legacy") {
      const next = new URLSearchParams({ procedure: procedureId, version });
      router.replace(`/builder?${next.toString()}`);
    }
  }, [procedureId, router, searchParams, version]);

  useEffect(() => {
    async function load() {
      try {
        const [proc, vers] = await Promise.all([
          getProcedure(procedureId, version),
          listVersions(procedureId),
        ]);
        setProcedure(proc);
        setCkpText(JSON.stringify(proc.ckp_json, null, 2));
        setVersions(vers);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [procedureId, version]);

  async function refreshReleaseReadiness(procOverride?: ProcedureDetail | null) {
    const target = procOverride ?? procedure;
    if (!target) {
      const idleState: ReleaseReadinessState = { status: "idle", issues: [], checkedVersion: null };
      setReleaseReadiness(idleState);
      return idleState;
    }

    setReleaseReadiness({ status: "checking", issues: [], checkedVersion: target.version });
    try {
      const report = await explainProcedure(target.procedure_id, target.version);
      const issues: string[] = [];
      if (report.nodes.length === 0) {
        issues.push("Workflow does not compile into any executable nodes.");
      }
      if (report.variables.missing_inputs.length > 0) {
        issues.push(`Missing required inputs: ${report.variables.missing_inputs.join(", ")}`);
      }

      const nextState: ReleaseReadinessState = {
        status: issues.length > 0 ? "blocked" : "ready",
        issues,
        checkedVersion: target.version,
      };
      setReleaseReadiness(nextState);
      return nextState;
    } catch (err) {
      const nextState: ReleaseReadinessState = {
        status: "blocked",
        issues: [err instanceof Error ? err.message : "Compiler preview failed"],
        checkedVersion: target.version,
      };
      setReleaseReadiness(nextState);
      return nextState;
    }
  }

  useEffect(() => {
    if (!procedure) return;
    void refreshReleaseReadiness(procedure);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [procedure?.procedure_id, procedure?.version, ckpText]);

  // Auto-load graph/explain data when landing directly via ?tab=graph or ?tab=explain
  useEffect(() => {
    if (!procedure) return;
    if (activeTab === "graph" && !graphData && !graphLoading) {
      setGraphLoading(true);
      setGraphError("");
      getGraph(procedure.procedure_id, procedure.version)
        .then((data) => setGraphData(data as any))
        .catch((err) => {
          console.error("Failed to load graph:", err);
          setGraphError(err instanceof Error ? err.message : "Failed to load graph");
        })
        .finally(() => setGraphLoading(false));
    }
    if (activeTab === "explain" && !explainResult && !explainLoading) {
      setExplainLoading(true);
      setExplainError(null);
      explainProcedure(procedure.procedure_id, procedure.version)
        .then(setExplainResult)
        .catch((err) => setExplainError(err instanceof Error ? err.message : "Explain failed"))
        .finally(() => setExplainLoading(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [procedure, activeTab]);

  // Flatten the nested { required: { varName: meta }, optional: { varName: meta } } CKP schema format
  function flattenSchema(raw: Record<string, any>): Record<string, any> {
    const keys = Object.keys(raw);
    const isNested = keys.length > 0 && keys.every(k => k === "required" || k === "optional");
    if (!isNested) return raw;
    const flat: Record<string, any> = {};
    for (const [varName, meta] of Object.entries((raw.required ?? {}) as Record<string, any>)) {
      flat[varName] = { required: true, ...(meta as Record<string, any>) };
    }
    for (const [varName, meta] of Object.entries((raw.optional ?? {}) as Record<string, any>)) {
      flat[varName] = { required: false, ...(meta as Record<string, any>) };
    }
    return flat;
  }
  const schema = flattenSchema((procedure?.ckp_json as any)?.variables_schema ?? {});
  const schemaEntries = Object.entries(schema) as [string, any][];
  // Required fields with no default — user MUST provide input
  const mustFillEntries = schemaEntries.filter(([, meta]) => !!(meta as any)?.required && (meta as any)?.default === undefined);
  // Fields that have a default, or are optional — user CAN override
  const overrideEntries = schemaEntries.filter(([, meta]) => !(meta as any)?.required || (meta as any)?.default !== undefined);

  function fieldRow(key: string, meta: Record<string, any>, showDefault = false) {
    const validation = (meta?.validation ?? {}) as Record<string, any>;
    const allowed = validation.allowed_values as string[] | undefined;
    const isRequired = !!meta?.required;
    const hasDefault = meta?.default !== undefined;
    const isSensitive = isFieldSensitive(meta as Record<string, unknown>);
    const currentVal = varsForm[key] ?? "";
    const isUsingDefault = hasDefault && currentVal === String(meta.default);
    const fieldErr = varsErrors[key];
    const borderCls = fieldErr
      ? "border-red-400 focus:border-red-500"
      : showDefault && isUsingDefault
        ? "border-neutral-200 bg-neutral-50 focus:border-sky-500 focus:bg-white"
        : "border-neutral-300 focus:border-sky-500";
    return (
      <div key={key}>
        <div className="mb-1 flex flex-wrap items-baseline gap-x-2">
          <label className="text-xs font-semibold text-neutral-700">
            {key}{isRequired && <span className="ml-0.5 text-red-500">*</span>}
          </label>
          {meta?.type && <span className="text-[10px] uppercase tracking-wide text-neutral-400">{meta.type as string}</span>}
          {isSensitive && <span className="text-[10px] text-yellow-600 font-medium">🔒 sensitive</span>}
          {showDefault && hasDefault && !isSensitive && (
            <span className="ml-auto text-[10px] text-neutral-400">
              default: <code className="font-mono">{String(meta.default)}</code>
              {!isUsingDefault && (
                <button type="button" onClick={() => handleVarChange(key, String(meta.default), meta)} className="ml-1 text-sky-700 hover:underline">restore</button>
              )}
            </span>
          )}
        </div>
        {meta?.description && <p className="mb-1.5 text-xs text-neutral-400">{meta.description as string}</p>}
        {allowed ? (
          <select aria-label={key} value={currentVal} onChange={(e) => handleVarChange(key, e.target.value, meta)} className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}>
            <option value="">— select —</option>
            {allowed.map((v: string) => <option key={v} value={v}>{v}</option>)}
          </select>
        ) : meta?.type === "array" || meta?.type === "object" ? (
          <textarea value={currentVal} onChange={(e) => handleVarChange(key, e.target.value, meta)} placeholder={meta?.type === "array" ? '["item1","item2"]' : '{"key":"value"}'} rows={3} className={`w-full rounded-lg border p-2 font-mono text-sm focus:outline-none ${borderCls}`} />
        ) : (
          <input
            type={isSensitive ? "password" : meta?.type === "number" ? "number" : "text"}
            value={currentVal}
            onChange={(e) => handleVarChange(key, e.target.value, meta)}
            placeholder={hasDefault && !isSensitive ? String(meta.default) : ""}
            autoComplete="off"
            className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}
          />
        )}
        {fieldErr ? (
          <p className="mt-1 text-xs text-red-500">{fieldErr}</p>
        ) : (
          <span className="mt-1 inline-flex gap-3">
            {validation.regex && <span className="text-xs text-neutral-400">Pattern: <code className="font-mono">{validation.regex as string}</code></span>}
            {validation.min !== undefined && <span className="text-xs text-neutral-400">Min: {validation.min as number}</span>}
            {validation.max !== undefined && <span className="text-xs text-neutral-400">Max: {validation.max as number}</span>}
          </span>
        )}
      </div>
    );
  }

  function openStartRun() {
    if (!procedure) return;
    if (procedure.status === "draft") {
      toast("Warning: this procedure is in DRAFT status. It may be incomplete.", "info");
    }
    // Pre-fill all fields with their defaults
    const defaults: Record<string, string> = {};
    schemaEntries.forEach(([k, v]) => {
      defaults[k] = v?.default !== undefined ? String(v.default) : "";
    });
    // Always show modal so callers can attach optional run context like case_id.
    setVarsForm(defaults);
    setVarsErrors({});
    setShowVarsModal(true);
  }

  async function doCreateRun(vars: Record<string, unknown>) {
    if (!procedure) return;
    setRunCreating(true);
    try {
      // Validate case if provided
      if (runCaseId.trim()) {
        try {
          await getCase(runCaseId.trim());
        } catch (err) {
          if (isNotFoundError(err)) {
            toast("Case not found. Please check the case ID.", "error");
            setRunCreating(false);
            return;
          }
          throw err;
        }
      }

      const run = await createRun(
        procedure.procedure_id,
        procedure.version,
        vars,
        { case_id: runCaseId.trim() || undefined }
      );
      router.push(`/runs/${run.run_id}`);
    } catch (err) {
      if (isNotFoundError(err)) {
        toast("Case not found. Please check the case ID.", "error");
      } else {
        console.error(err);
      }
      setRunCreating(false);
    }
  }

  function validateVarField(key: string, raw: string, meta: Record<string, any>): string {
    const validation = (meta?.validation ?? {}) as Record<string, any>;
    const vtype = (meta?.type ?? "string") as string;
    if (meta?.required && !raw.trim()) return "This field is required";
    if (!raw) return "";
    if (validation.regex) {
      try {
        if (!new RegExp(`^(?:${validation.regex as string})$`).test(raw))
          return `Must match pattern: ${validation.regex as string}`;
      } catch { /* invalid regex — skip */ }
    }
    if (vtype === "number") {
      const num = Number(raw);
      if (validation.min !== undefined && num < (validation.min as number))
        return `Minimum value is ${validation.min as number}`;
      if (validation.max !== undefined && num > (validation.max as number))
        return `Maximum value is ${validation.max as number}`;
    }
    const allowed = validation.allowed_values as string[] | undefined;
    if (allowed && !allowed.includes(raw)) return `Must be one of: ${allowed.join(", ")}`;
    return "";
  }

  function handleVarChange(key: string, raw: string, meta: Record<string, any>) {
    setVarsForm((prev) => ({ ...prev, [key]: raw }));
    const err = validateVarField(key, raw, meta);
    setVarsErrors((prev) => {
      const next = { ...prev };
      if (err) next[key] = err;
      else delete next[key];
      return next;
    });
  }

  async function handleSaveCkp() {
    if (!procedure) return;
    try {
      const parsed = JSON.parse(ckpText);
      await updateProcedure(procedure.procedure_id, procedure.version, parsed);
      const refreshed = await getProcedure(procedure.procedure_id, procedure.version);
      setProcedure(refreshed);
      setEditMode(false);
      await refreshReleaseReadiness(refreshed);
    } catch (err) {
      console.error(err);
      toast(err instanceof Error ? err.message : "Failed to save workflow", "error");
    }
  }

  async function handleDeleteVersion() {
    if (!procedure) return;
    setConfirmDelete(true);
  }

  async function doDeleteVersion() {
    if (!procedure) return;
    setConfirmDelete(false);
    try {
      await deleteProcedure(procedure.procedure_id, procedure.version);
      router.push("/procedures");
    } catch (err) {
      console.error(err);
      toast(err instanceof Error ? err.message : "Failed to delete workflow", "error");
    }
  }

  async function handlePromote(targetChannel: ReleaseChannel) {
    if (!procedure) return;
    const readiness =
      releaseReadiness.checkedVersion === procedure.version && releaseReadiness.status !== "idle"
        ? releaseReadiness
        : await refreshReleaseReadiness(procedure);

    if (readiness.status === "blocked") {
      toast(
        readiness.issues[0] ?? "Procedure is not ready for promotion.",
        "error"
      );
      setActiveTab("explain");
      return;
    }

    setPromotingTo(targetChannel);
    try {
      const result = await promoteProcedure(procedure.procedure_id, procedure.version, targetChannel);
      const [refreshed, vers] = await Promise.all([
        getProcedure(procedure.procedure_id, procedure.version),
        listVersions(procedure.procedure_id),
      ]);
      setProcedure(refreshed);
      setVersions(vers);
      const previousMsg = result.previous_channel_version
        ? ` Replaced ${targetChannel} active version ${result.previous_channel_version}.`
        : "";
      toast(`Promoted to ${targetChannel.toUpperCase()}.${previousMsg}`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Promotion failed", "error");
    } finally {
      setPromotingTo(null);
    }
  }

  function openRollbackModal() {
    if (!procedure) return;
    const preferredTarget = procedure.promoted_from_version;
    const hasPreferredTarget = !!preferredTarget && rollbackCandidates.some((v) => v.version === preferredTarget);
    const defaultTarget = hasPreferredTarget ? (preferredTarget as string) : (rollbackCandidates[0]?.version ?? "");
    if (!defaultTarget) {
      toast("No rollback target is available for this version", "error");
      return;
    }
    setRollbackTargetVersion(defaultTarget);
    setShowRollbackModal(true);
  }

  async function handleRollback() {
    if (!procedure) return;
    const currentChannel = (procedure.release_channel ?? "dev") as ReleaseChannel;
    if (!rollbackTargetVersion) {
      toast("Select a rollback target version", "error");
      return;
    }

    setRollingBack(true);
    try {
      const result = await rollbackProcedure(
        procedure.procedure_id,
        procedure.version,
        currentChannel,
        rollbackTargetVersion
      );
      const [refreshed, vers] = await Promise.all([
        getProcedure(result.restored.procedure_id, result.restored.version),
        listVersions(procedure.procedure_id),
      ]);
      setProcedure(refreshed);
      setVersions(vers);
      if (result.restored.version !== procedure.version) {
        router.push(`/procedures/${encodeURIComponent(result.restored.procedure_id)}/${encodeURIComponent(result.restored.version)}`);
      }
      setShowRollbackModal(false);
      toast(
        `Rolled back ${result.replaced_version} to ${result.restored.version} in ${currentChannel.toUpperCase()}.`,
        "success"
      );
    } catch (err) {
      toast(err instanceof Error ? err.message : "Rollback failed", "error");
    } finally {
      setRollingBack(false);
    }
  }

  if (loading) return <p className="text-neutral-500">Loading procedure...</p>;
  if (!procedure) return <p className="text-red-500">Procedure not found</p>;

  const currentReleaseChannel = (procedure.release_channel ?? "dev") as ReleaseChannel;
  const nextReleaseChannel = getNextReleaseChannel(currentReleaseChannel);
  const rollbackCandidates = versions.filter((v) => {
    if (v.version === procedure.version) return false;
    if ((v.release_channel ?? "dev") !== currentReleaseChannel) return false;
    return v.status !== "archived" && v.status !== "draft";
  });
  const canRollback = rollbackCandidates.length > 0;

  const ckp = procedure.ckp_json;
  const wfNodes = (ckp as any)?.workflow_graph?.nodes ?? {};
  const nodeEntries = Object.entries(wfNodes);

  // Lazy-load graph data when tab is selected
  async function loadGraph() {
    if (graphData || graphLoading || !procedure) return;
    setGraphLoading(true);
    setGraphError("");
    try {
      const data = await getGraph(procedure.procedure_id, procedure.version);
      setGraphData(data as any);
    } catch (err) {
      console.error("Failed to load graph:", err);
      setGraphError(err instanceof Error ? err.message : "Failed to load graph");
    } finally {
      setGraphLoading(false);
    }
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] space-y-4 bg-neutral-50 p-6">
      <section className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex items-start justify-between">
        <div>
          <Link href="/procedures" className="text-sm text-sky-700 hover:underline">
            ← Procedures
          </Link>
          <h2 className="mt-2 text-2xl font-semibold text-neutral-900">{procedure.name}</h2>
          <div className="mt-1 flex items-center gap-2">
            <StatusBadge status={procedure.status ?? "draft"} />
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${releaseChannelBadgeClass(procedure.release_channel)}`}
            >
              {currentReleaseChannel}
            </span>
            {procedure.effective_date && (
              <span className="text-xs text-neutral-400">Effective: {procedure.effective_date}</span>
            )}
          </div>
          <p className="mt-1 text-sm text-neutral-500">{procedure.description}</p>
          <p className="mt-1 text-xs text-neutral-400">
            ID: {procedure.procedure_id} · Version: {procedure.version}
          </p>
          {(procedure.promoted_at || procedure.promoted_by || procedure.promoted_from_version) && (
            <p className="mt-1 text-xs text-neutral-400">
              {procedure.promoted_at ? `Promoted ${new Date(procedure.promoted_at).toLocaleString()}` : "Promoted"}
              {procedure.promoted_by ? ` by ${procedure.promoted_by}` : ""}
              {procedure.promoted_from_version ? ` from v${procedure.promoted_from_version}` : ""}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {releaseReadiness.status === "checking" ? (
            <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-sky-700">
              checking release readiness
            </span>
          ) : null}
          {releaseReadiness.status === "ready" ? (
            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
              release ready
            </span>
          ) : null}
          {releaseReadiness.status === "blocked" ? (
            <span className="rounded-full border border-red-200 bg-red-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-red-700">
              promotion blocked
            </span>
          ) : null}
          {canRollback && (
            <button
              onClick={openRollbackModal}
              disabled={rollingBack || promotingTo !== null}
              className="rounded-full border border-orange-300 px-4 py-2 text-sm font-medium text-orange-700 hover:bg-orange-50 disabled:opacity-60"
            >
              {rollingBack ? "Rolling back..." : "Rollback..."}
            </button>
          )}
          {!canRollback && (
            <span className="text-xs text-neutral-400">
              No same-channel rollback targets available
            </span>
          )}
          {nextReleaseChannel && (
            <button
              onClick={() => handlePromote(nextReleaseChannel)}
              disabled={promotingTo !== null || rollingBack || releaseReadiness.status === "checking"}
              className="rounded-full border border-indigo-300 px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-60"
            >
              {promotingTo === nextReleaseChannel
                ? `Promoting to ${nextReleaseChannel.toUpperCase()}...`
                : `Promote to ${nextReleaseChannel.toUpperCase()}`}
            </button>
          )}
          <button
            onClick={() => {
              const next = new URLSearchParams({ procedure: procedure.procedure_id, version: procedure.version });
              router.push(`/builder?${next.toString()}`);
            }}
            className="rounded-full border border-sky-300 px-4 py-2 text-sm font-medium text-sky-700 hover:bg-sky-50"
          >
            Open Builder
          </button>
          <button
            onClick={openStartRun}
            disabled={runCreating}
            title={procedure.status === "draft" ? "This procedure is in DRAFT status" : undefined}
            className={`rounded-full px-4 py-2 text-sm font-medium text-white disabled:opacity-50 ${procedure.status === "draft"
                ? "bg-green-600 hover:bg-green-700 ring-2 ring-amber-400 ring-offset-1"
                : "bg-green-600 hover:bg-green-700"
              }`}
          >
            {runCreating ? "Starting\u2026" : procedure.status === "draft" ? "Start Run (draft)" : "Start Run"}
          </button>
          <button
            onClick={() => setEditMode((prev) => !prev)}
            className="rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            {editMode ? "Cancel Edit" : "Edit CKP"}
          </button>
          <button
            onClick={handleDeleteVersion}
            className="rounded-full border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
          >
            Delete Version
          </button>
        </div>
      </div>
      </section>

      {releaseReadiness.status === "blocked" && releaseReadiness.issues.length > 0 ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <p className="font-semibold">Promotion is blocked until compiler readiness issues are resolved.</p>
          <p className="mt-1">{releaseReadiness.issues[0]}</p>
        </div>
      ) : null}

      <div className="rounded-2xl border border-neutral-200 bg-white shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex border-b border-neutral-200">
        {(["overview", "graph", "explain", "ckp", "versions", "runs", "trigger"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => {
              setActiveTab(tab);
              if (tab === "graph") loadGraph();
              if (tab === "explain" && !explainResult && !explainLoading) {
                setExplainLoading(true);
                setExplainError(null);
                explainProcedure(procedureId, version)
                  .then(setExplainResult)
                  .catch((err) => {
                    const msg = err instanceof Error ? err.message : "Explain failed";
                    setExplainError(msg);
                  })
                  .finally(() => setExplainLoading(false));
              }
              if (tab === "runs" && procedureRuns.length === 0 && !runsLoading) {
                setRunsLoading(true);
                listRuns({ procedure_id: procedureId })
                  .then(setProcedureRuns)
                  .catch(console.error)
                  .finally(() => setRunsLoading(false));
              }
              if (tab === "trigger" && !triggerFetched) {
                setTriggerFetched(true);
                setTriggerLoading(true);
                getTrigger(procedureId, version)
                  .then((r) => {
                    if (r) {
                      setTriggerReg(r);
                      setTriggerForm({
                        trigger_type: r.trigger_type,
                        schedule: r.schedule ?? "",
                        webhook_secret: r.webhook_secret ?? "",
                        event_source: r.event_source ?? "",
                        dedupe_window_seconds: r.dedupe_window_seconds,
                        max_concurrent_runs: r.max_concurrent_runs != null ? String(r.max_concurrent_runs) : "",
                        enabled: r.enabled,
                      });
                    } else {
                      // No registration yet — pre-populate from CKP trigger field if present
                      const t = procedure?.trigger as Record<string, unknown> | null | undefined;
                      if (t) {
                        setTriggerForm(f => ({
                          ...f,
                          trigger_type: (t.type as string) ?? f.trigger_type,
                          schedule: (t.schedule as string) ?? "",
                          webhook_secret: (t.webhook_secret as string) ?? "",
                        }));
                      }
                    }
                  })
                  .catch(console.error)
                  .finally(() => setTriggerLoading(false));
              }
            }}
            className={`px-5 py-3 text-sm font-medium transition ${activeTab === tab
                ? "border-b-2 border-sky-600 text-sky-600"
                : "text-neutral-500 hover:text-neutral-700"
              }`}
          >
            {tab === "ckp" ? "CKP Source" : tab === "graph" ? "Workflow Graph" : tab === "explain" ? "Explain" : tab === "trigger" ? "Trigger" : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {activeTab === "overview" && (
        <div className="p-6">
          <h3 className="mb-4 text-sm font-semibold text-neutral-900">Workflow Nodes ({nodeEntries.length})</h3>
          <div className="space-y-3">
            {nodeEntries.map(([nodeId, node]: [string, any]) => (
              <div key={nodeId} className="flex items-center gap-3 rounded-lg border border-neutral-100 p-3">
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold text-white ${NODE_TYPE_BADGE_CLASS[node.type as string] ?? "bg-neutral-500"}`}>{node.type}</span>
                <div>
                  <p className="text-sm font-medium">{nodeId}</p>
                  {node.description && <p className="text-xs text-neutral-400">{node.description}</p>}
                  {node.agent && <p className="text-xs text-neutral-400">Agent: {node.agent}</p>}
                </div>
              </div>
            ))}
          </div>
          {/* Provenance */}
          {procedure.provenance && (
            <div className="mt-6">
              <h4 className="mb-2 text-xs font-semibold text-neutral-500 uppercase tracking-wide">Provenance</h4>
              <pre className="rounded-lg bg-neutral-50 p-3 text-xs font-mono overflow-auto">
                {JSON.stringify(procedure.provenance, null, 2)}
              </pre>
            </div>
          )}
          {/* Retrieval Metadata */}
          {procedure.retrieval_metadata && (
            <div className="mt-4">
              <h4 className="mb-2 text-xs font-semibold text-neutral-500 uppercase tracking-wide">Retrieval Metadata</h4>
              {Array.isArray((procedure.retrieval_metadata as any)?.tags) && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {((procedure.retrieval_metadata as any).tags as string[]).map((tag: string) => (
                    <span key={tag} className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] text-blue-700">{tag}</span>
                  ))}
                </div>
              )}
              <pre className="rounded-lg bg-neutral-50 p-3 text-xs font-mono overflow-auto">
                {JSON.stringify(procedure.retrieval_metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {activeTab === "graph" && (
        <div className="p-6 space-y-3">
          <div className="flex items-center justify-between rounded-2xl border border-sky-100 bg-sky-50 px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-sky-900">Graph preview only</p>
              <p className="text-xs text-sky-700">
                Editing now happens in the dedicated Visual Builder workspace so the canvas has full room and cleaner navigation.
              </p>
            </div>
            <button
              onClick={() => {
                const next = new URLSearchParams({ procedure: procedure.procedure_id, version: procedure.version });
                router.push(`/builder?${next.toString()}`);
              }}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700"
            >
              Open Builder
            </button>
          </div>
          {graphLoading && <p className="text-sm text-neutral-400">Loading graph...</p>}
          {graphError && <p className="text-sm text-red-500">{graphError}</p>}
          {graphData && <WorkflowGraph graph={graphData} />}
          {!graphLoading && !graphData && !graphError && (
            <p className="text-sm text-neutral-400">No graph data available.</p>
          )}
        </div>
      )}

      {activeTab === "ckp" && (
        <div className="p-6">
          {editMode ? (
            <div className="space-y-3">
              <textarea
                value={ckpText}
                onChange={(e) => setCkpText(e.target.value)}
                title="CKP JSON editor"
                placeholder="Paste CKP JSON"
                className="h-[600px] w-full rounded-lg border border-neutral-300 p-3 font-mono text-xs"
              />
              <button
                onClick={handleSaveCkp}
                className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700"
              >
                Save CKP
              </button>
            </div>
          ) : (
            <pre className="max-h-[600px] overflow-auto rounded-lg bg-neutral-50 p-4 font-mono text-xs leading-relaxed">
              {JSON.stringify(ckp, null, 2)}
            </pre>
          )}
        </div>
      )}

      {activeTab === "explain" && (
        <div className="p-6">
          {explainLoading ? (
            <div className="flex items-center gap-2 text-sm text-neutral-400">
              <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Analysing procedure…
            </div>
          ) : explainError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4">
              <p className="text-sm font-semibold text-red-700">Analysis failed</p>
              <p className="mt-1 text-xs text-red-600 font-mono">{explainError}</p>
              <button
                onClick={() => {
                  setExplainError(null);
                  setExplainLoading(true);
                  explainProcedure(procedureId, version)
                    .then(setExplainResult)
                    .catch((err) => setExplainError(err instanceof Error ? err.message : "Explain failed"))
                    .finally(() => setExplainLoading(false));
                }}
                className="mt-2 text-xs text-red-600 underline hover:text-red-800"
              >
                Retry
              </button>
            </div>
          ) : !explainResult ? (
            <p className="text-sm text-neutral-400">Click the Explain tab to analyse this procedure.</p>
          ) : (
            <div className="space-y-6">
              {/* Route Trace */}
              <div>
                <h4 className="mb-2 text-xs font-semibold text-neutral-500 uppercase tracking-wide">Execution Route</h4>
                <div className="flex flex-wrap items-center gap-1">
                  {explainResult.route_trace.map((entry, i) => (
                    <span key={i} className="flex items-center gap-1">
                      {i > 0 && <span className="text-neutral-300">→</span>}
                      <span className={`rounded px-2 py-0.5 text-xs font-mono ${entry.is_terminal ? "bg-neutral-100 text-neutral-500" : "bg-sky-50 text-sky-800"
                        }`}>
                        {entry.node_id}
                        <span className="ml-1 text-[10px] opacity-60">({entry.type})</span>
                      </span>
                    </span>
                  ))}
                </div>
              </div>

              {/* Variables */}
              <div>
                <h4 className="mb-2 text-xs font-semibold text-neutral-500 uppercase tracking-wide">Variables</h4>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <div className="rounded-lg border border-neutral-100 p-3">
                    <p className="text-[10px] text-neutral-500">Required</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {explainResult.variables.required.length === 0 ? <span className="text-xs text-neutral-400">None</span> : explainResult.variables.required.map((v) => (
                        <span key={v} className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${explainResult.variables.provided.includes(v) ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
                          }`}>{v}</span>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-lg border border-neutral-100 p-3">
                    <p className="text-[10px] text-neutral-500">Produced</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {explainResult.variables.produced.length === 0 ? <span className="text-xs text-neutral-400">None</span> : explainResult.variables.produced.map((v) => (
                        <span key={v} className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700">{v}</span>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-lg border border-neutral-100 p-3">
                    <p className="text-[10px] text-neutral-500">Missing</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {(explainResult.variables.missing_inputs ?? []).length === 0 ? <span className="text-xs text-green-500">All satisfied</span> : (explainResult.variables.missing_inputs ?? []).map((v) => (
                        <span key={v} className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] text-red-700">{v}</span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Nodes */}
              <div>
                <h4 className="mb-2 text-xs font-semibold text-neutral-500 uppercase tracking-wide">Nodes ({explainResult.nodes.length})</h4>
                <div className="space-y-2">
                  {explainResult.nodes.map((node) => (
                    <div key={node.id} className="rounded-lg border border-neutral-100 p-3">
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] font-semibold text-neutral-600">{node.type}</span>
                        <span className="font-mono text-sm font-medium text-neutral-900">{node.id}</span>
                        {node.agent && <span className="text-xs text-neutral-400">agent: {node.agent}</span>}
                        {node.has_side_effects && <span className="rounded bg-yellow-50 px-1.5 py-0.5 text-[10px] text-yellow-600">side-effects</span>}
                        {node.is_checkpoint && <span className="rounded bg-teal-50 px-1.5 py-0.5 text-[10px] text-teal-600">checkpoint</span>}
                        {node.timeout_ms && <span className="text-[10px] text-neutral-400">timeout: {node.timeout_ms}ms</span>}
                      </div>
                      {node.description && <p className="mt-1 text-xs text-neutral-500">{node.description}</p>}
                      {node.sla && <p className="mt-1 text-[10px] text-orange-500">SLA: {JSON.stringify(node.sla)}</p>}
                      {node.steps.length > 0 && (
                        <div className="mt-2 border-t border-neutral-50 pt-2">
                          <p className="text-[10px] text-neutral-400 mb-1">Steps:</p>
                          <div className="flex flex-wrap gap-1">
                            {node.steps.map((s) => (
                              <span key={s.step_id} className="rounded bg-neutral-50 px-1.5 py-0.5 text-[10px] text-neutral-600">{s.step_id}: {s.action}{s.binding_kind ? ` [${s.binding_kind}]` : ""}</span>
                            ))}
                          </div>
                        </div>
                      )}
                      {node.error_handlers.length > 0 && (
                        <div className="mt-1">
                          <p className="text-[10px] text-red-400">Error handlers: {node.error_handlers.map(h => `${h.error_type}→${h.action}`).join(", ")}</p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* External Calls */}
              {explainResult.external_calls.length > 0 && (
                <div>
                  <h4 className="mb-2 text-xs font-semibold text-neutral-500 uppercase tracking-wide">External Calls ({explainResult.external_calls.length})</h4>
                  <div className="overflow-auto">
                    <table className="w-full text-xs">
                      <thead><tr className="border-b text-left text-neutral-500"><th className="pb-1 pr-3">Node</th><th className="pb-1 pr-3">Step</th><th className="pb-1 pr-3">Action</th><th className="pb-1 pr-3">Binding</th><th className="pb-1">Ref</th></tr></thead>
                      <tbody>
                        {explainResult.external_calls.map((call, i) => (
                          <tr key={i} className="border-b last:border-0">
                            <td className="py-1 pr-3 font-mono">{call.node_id}</td>
                            <td className="py-1 pr-3 font-mono">{call.step_id ?? "—"}</td>
                            <td className="py-1 pr-3">{call.action}</td>
                            <td className="py-1 pr-3"><span className="rounded bg-blue-50 px-1 text-blue-600">{call.binding_kind}</span></td>
                            <td className="py-1 font-mono text-neutral-500">{call.binding_ref ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Edges */}
              <div>
                <h4 className="mb-2 text-xs font-semibold text-neutral-500 uppercase tracking-wide">Edges ({explainResult.edges.length})</h4>
                <div className="flex flex-wrap gap-1">
                  {explainResult.edges.map((edge, i) => (
                    <span key={i} className="rounded bg-neutral-50 px-2 py-0.5 text-[10px] text-neutral-600">
                      {edge.from} → {edge.to}{edge.condition ? ` [${edge.condition}]` : ""}
                    </span>
                  ))}
                </div>
              </div>

              {/* Policy Summary */}
              {Object.keys(explainResult.policy_summary).length > 0 && (
                <div>
                  <h4 className="mb-2 text-xs font-semibold text-neutral-500 uppercase tracking-wide">Policy Summary</h4>
                  <pre className="rounded-lg bg-neutral-50 p-3 font-mono text-xs">{JSON.stringify(explainResult.policy_summary, null, 2)}</pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {activeTab === "versions" && (
        <div className="p-6">
          {versions.length === 0 ? (
            <p className="text-sm text-neutral-400">No other versions</p>
          ) : (
            <div className="space-y-4">
              {/* Version list */}
              <div className="space-y-2">
                {versions.map((v) => (
                  <div key={v.version} className="flex items-center justify-between rounded-lg border border-neutral-100 p-3">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/procedures/${encodeURIComponent(v.procedure_id)}/${encodeURIComponent(v.version)}`}
                        className={`text-sm font-medium ${v.version === version ? "text-sky-700 font-bold" : "text-neutral-700 hover:text-sky-700"}`}
                      >
                        v{v.version} {v.version === version && "(current)"}
                      </Link>
                      <span
                        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${releaseChannelBadgeClass(v.release_channel)}`}
                      >
                        {(v.release_channel ?? "dev").toUpperCase()}
                      </span>
                      {v.promoted_by && (
                        <span className="text-xs text-neutral-400">by {v.promoted_by}</span>
                      )}
                    </div>
                    <span className="text-xs text-neutral-400">{new Date(v.created_at).toLocaleString()}</span>
                  </div>
                ))}
              </div>

              {/* Diff Comparison */}
              {versions.length >= 2 && (
                <div className="border-t border-neutral-200 pt-4">
                  <h4 className="mb-3 text-sm font-semibold text-neutral-900">Compare Versions</h4>
                  <div className="flex flex-wrap items-center gap-3 mb-3">
                    <select
                      value={diffVersionA}
                      onChange={(e) => setDiffVersionA(e.target.value)}
                      aria-label="Base version"
                      className="rounded-md border border-neutral-300 px-2 py-1 text-xs"
                    >
                      <option value="">Base version…</option>
                      {versions.map((v) => (<option key={v.version} value={v.version}>v{v.version}</option>))}
                    </select>
                    <span className="text-xs text-neutral-400">vs</span>
                    <select
                      value={diffVersionB}
                      onChange={(e) => setDiffVersionB(e.target.value)}
                      aria-label="Compare version"
                      className="rounded-md border border-neutral-300 px-2 py-1 text-xs"
                    >
                      <option value="">Compare version…</option>
                      {versions.map((v) => (<option key={v.version} value={v.version}>v{v.version}</option>))}
                    </select>
                    <button
                      disabled={!diffVersionA || !diffVersionB || diffVersionA === diffVersionB || diffLoading}
                      onClick={async () => {
                        if (!diffVersionA || !diffVersionB) return;
                        setDiffLoading(true);
                        try {
                          const [procA, procB] = await Promise.all([
                            getProcedure(procedureId, diffVersionA),
                            getProcedure(procedureId, diffVersionB),
                          ]);
                          const left = JSON.stringify(procA.ckp_json, null, 2);
                          const right = JSON.stringify(procB.ckp_json, null, 2);
                          const hunks = computeLineDiff(left, right);
                          setDiffResult({ left, right, hunks });
                        } catch (err) {
                          toast(err instanceof Error ? err.message : "Failed to load versions", "error");
                        } finally {
                          setDiffLoading(false);
                        }
                      }}
                      className="rounded-md bg-sky-600 px-3 py-1 text-xs font-medium text-white hover:bg-sky-700 disabled:opacity-50"
                    >
                      {diffLoading ? "Loading…" : "Compare"}
                    </button>
                  </div>

                  {/* Diff output */}
                  {diffResult && (
                    <div className="rounded-lg border border-neutral-200 overflow-auto max-h-[600px]">
                      <table className="w-full font-mono text-xs">
                        <thead>
                          <tr className="border-b bg-neutral-50 text-neutral-500">
                            <th className="px-2 py-1 text-right w-10">v{diffVersionA}</th>
                            <th className="px-2 py-1 text-right w-10">v{diffVersionB}</th>
                            <th className="px-3 py-1 text-left">Line</th>
                          </tr>
                        </thead>
                        <tbody>
                          {diffResult.hunks.map((h, i) => (
                            <tr
                              key={i}
                              className={
                                h.type === "added"
                                  ? "bg-green-50"
                                  : h.type === "removed"
                                    ? "bg-red-50"
                                    : ""
                              }
                            >
                              <td className="px-2 py-0.5 text-right text-neutral-400 select-none border-r border-neutral-100">
                                {h.lineA ?? ""}
                              </td>
                              <td className="px-2 py-0.5 text-right text-neutral-400 select-none border-r border-neutral-100">
                                {h.lineB ?? ""}
                              </td>
                              <td className="px-3 py-0.5 whitespace-pre">
                                <span className={
                                  h.type === "added"
                                    ? "text-green-700"
                                    : h.type === "removed"
                                      ? "text-red-700"
                                      : "text-neutral-700"
                                }>
                                  {h.type === "added" ? "+ " : h.type === "removed" ? "- " : "  "}{h.text}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <div className="border-t border-neutral-200 bg-neutral-50 px-3 py-2 flex items-center gap-4 text-xs text-neutral-500">
                        <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded bg-red-100 border border-red-200" /> Removed</span>
                        <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded bg-green-100 border border-green-200" /> Added</span>
                        <span className="ml-auto">{diffResult.hunks.filter(h => h.type !== "equal").length} change(s)</span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {activeTab === "runs" && (
        <div className="p-6">
          <h3 className="mb-4 text-sm font-semibold text-neutral-900">Runs for this procedure</h3>
          {runsLoading ? (
            <p className="text-sm text-neutral-400">Loading runs…</p>
          ) : procedureRuns.length === 0 ? (
            <p className="text-sm text-neutral-400">No runs yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-100 text-xs text-neutral-500">
                  <th className="py-2 text-left font-medium">Run ID</th>
                  <th className="py-2 text-left font-medium">Status</th>
                  <th className="py-2 text-left font-medium">Started</th>
                  <th className="py-2 text-left font-medium">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {procedureRuns.map((r) => (
                  <tr key={r.run_id} className="hover:bg-neutral-50">
                    <td className="py-2">
                      <Link href={`/runs/${r.run_id}`} className="font-mono text-xs text-sky-700 hover:underline">
                        {r.run_id.slice(0, 14)}…
                      </Link>
                    </td>
                    <td className="py-2">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${r.status === "completed" ? "bg-green-100 text-green-700" :
                          r.status === "failed" ? "bg-red-100 text-red-700" :
                            r.status === "running" ? "bg-blue-100 text-blue-700" :
                              "bg-neutral-100 text-neutral-600"
                        }`}>{r.status}</span>
                    </td>
                    <td className="py-2 text-xs text-neutral-400">{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                    <td className="py-2 text-xs text-neutral-400">{r.duration_seconds != null ? `${r.duration_seconds.toFixed(1)}s` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Trigger tab ───────────────────────────────────── */}
      {activeTab === "trigger" && (
        <div className="p-6 space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-neutral-900">Trigger Configuration</h3>
              <p className="mt-0.5 text-xs text-neutral-400">
                Register an automated trigger for this procedure version. Scheduled triggers use cron
                syntax; webhooks accept POST requests with optional HMAC-SHA256 signature verification.
              </p>
            </div>
            {triggerReg && (
              <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-semibold ${triggerReg.enabled ? "bg-green-100 text-green-700" : "bg-neutral-100 text-neutral-500"
                }`}>
                {triggerReg.enabled ? "Active" : "Disabled"}
              </span>
            )}
          </div>

          {triggerLoading ? (
            <p className="text-sm text-neutral-400">Loading trigger info…</p>
          ) : (
            <div className="space-y-4">
              {/* Type selector */}
              <div>
                <label htmlFor="trigger_type" className="mb-1 block text-xs font-medium text-neutral-600">Trigger Type</label>
                <select
                  id="trigger_type"
                  value={triggerForm.trigger_type}
                  onChange={(e) => setTriggerForm((f) => ({ ...f, trigger_type: e.target.value }))}
                  className="rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none"
                >
                  <option value="webhook">Webhook (HTTP POST)</option>
                  <option value="scheduled">Scheduled (cron)</option>
                  <option value="event">Event (message bus)</option>
                  <option value="file_watch">File Watch</option>
                </select>
              </div>

              {/* Schedule — shown only for scheduled */}
              {triggerForm.trigger_type === "scheduled" && (
                <div>
                  <label htmlFor="trigger_schedule" className="mb-1 block text-xs font-medium text-neutral-600">
                    Cron Expression <span className="text-neutral-400">(UTC, 5-field)</span>
                  </label>
                  <input
                    id="trigger_schedule"
                    value={triggerForm.schedule}
                    onChange={(e) => setTriggerForm((f) => ({ ...f, schedule: e.target.value }))}
                    placeholder="e.g. 0 9 * * 1-5  (weekdays at 9am)"
                    className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm font-mono focus:border-sky-500 focus:outline-none"
                  />
                </div>
              )}

              {/* Webhook secret env var */}
              {triggerForm.trigger_type === "webhook" && (
                <>
                  <div>
                    <label htmlFor="trigger_webhook_secret" className="mb-1 block text-xs font-medium text-neutral-600">
                      Webhook Secret Env Var <span className="text-neutral-400">(optional — env var name holding HMAC key)</span>
                    </label>
                    <input
                      id="trigger_webhook_secret"
                      value={triggerForm.webhook_secret}
                      onChange={(e) => setTriggerForm((f) => ({ ...f, webhook_secret: e.target.value }))}
                      placeholder="e.g. MY_PROCEDURE_WEBHOOK_SECRET"
                      className="w-full rounded-lg border border-neutral-300 px-3 py-2 font-mono text-sm focus:border-sky-500 focus:outline-none"
                    />
                  </div>
                  <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs text-blue-700">
                    <strong>Webhook URL:</strong>{" "}
                    <code className="font-mono select-all">
                      {`${typeof window !== "undefined" ? window.location.origin : ""}/api/triggers/webhook/${encodeURIComponent(procedureId)}`}
                    </code>
                    <p className="mt-1 text-blue-600">
                      Send a POST to this URL. Include{" "}
                      <code className="font-mono">X-LangOrch-Signature: sha256=&lt;hmac&gt;</code> header when a secret is set.
                    </p>
                  </div>
                </>
              )}

              {/* Event source */}
              {triggerForm.trigger_type === "event" && (
                <div>
                  <label htmlFor="trigger_event_source" className="mb-1 block text-xs font-medium text-neutral-600">Event Source <span className="text-neutral-400">(Kafka topic / SQS queue)</span></label>
                  <input
                    id="trigger_event_source"
                    value={triggerForm.event_source}
                    onChange={(e) => setTriggerForm((f) => ({ ...f, event_source: e.target.value }))}
                    placeholder="e.g. orders.created"
                    className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none"
                  />
                </div>
              )}

              {/* Dedupe window + concurrency */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="trigger_dedupe_window" className="mb-1 block text-xs font-medium text-neutral-600">Dedupe Window (seconds)</label>
                  <input
                    id="trigger_dedupe_window"
                    type="number"
                    min={0}
                    value={triggerForm.dedupe_window_seconds}
                    onChange={(e) => setTriggerForm((f) => ({ ...f, dedupe_window_seconds: Number(e.target.value) }))}
                    className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none"
                  />
                  <p className="mt-0.5 text-[10px] text-neutral-400">0 = no dedupe</p>
                </div>
                <div>
                  <label htmlFor="trigger_max_concurrent_runs" className="mb-1 block text-xs font-medium text-neutral-600">Max Concurrent Runs</label>
                  <input
                    id="trigger_max_concurrent_runs"
                    type="number"
                    min={1}
                    value={triggerForm.max_concurrent_runs}
                    onChange={(e) => setTriggerForm((f) => ({ ...f, max_concurrent_runs: e.target.value }))}
                    placeholder="unlimited"
                    className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="trigger_enabled"
                  checked={triggerForm.enabled}
                  onChange={(e) => setTriggerForm((f) => ({ ...f, enabled: e.target.checked }))}
                  className="rounded"
                />
                <label htmlFor="trigger_enabled" className="text-sm text-neutral-700">Enabled</label>
              </div>

              {/* Action bar */}
              <div className="flex flex-wrap gap-2 pt-2 border-t border-neutral-100">
                <button
                  onClick={async () => {
                    setTriggerSaving(true);
                    try {
                      const reg = await upsertTrigger(procedureId, version, {
                        trigger_type: triggerForm.trigger_type,
                        schedule: triggerForm.schedule || null,
                        webhook_secret: triggerForm.webhook_secret || null,
                        event_source: triggerForm.event_source || null,
                        dedupe_window_seconds: triggerForm.dedupe_window_seconds,
                        max_concurrent_runs: triggerForm.max_concurrent_runs ? Number(triggerForm.max_concurrent_runs) : null,
                        enabled: triggerForm.enabled,
                      });
                      setTriggerReg(reg);
                      toast("Trigger saved", "success");
                    } catch (err) {
                      toast(err instanceof Error ? err.message : "Failed to save trigger", "error");
                    } finally {
                      setTriggerSaving(false);
                    }
                  }}
                  disabled={triggerSaving}
                  className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
                >
                  {triggerSaving ? "Saving…" : triggerReg ? "Update Trigger" : "Register Trigger"}
                </button>

                {triggerReg && (
                  <>
                    <button
                      onClick={async () => {
                        setTriggerFiring(true);
                        try {
                          const result = await fireTrigger(procedureId, version);
                          toast(`Run created: ${result.run_id.slice(0, 12)}…`, "success");
                        } catch (err) {
                          toast(err instanceof Error ? err.message : "Failed to fire trigger", "error");
                        } finally {
                          setTriggerFiring(false);
                        }
                      }}
                      disabled={triggerFiring}
                      className="rounded-lg border border-green-300 bg-green-50 px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-100 disabled:opacity-50"
                    >
                      {triggerFiring ? "Firing…" : "Fire Now"}
                    </button>
                    <button
                      onClick={async () => {
                        try {
                          await deleteTrigger(procedureId, version);
                          setTriggerReg(null);
                          toast("Trigger disabled", "success");
                        } catch (err) {
                          toast(err instanceof Error ? err.message : "Failed to remove trigger", "error");
                        }
                      }}
                      className="rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
                    >
                      Disable
                    </button>
                  </>
                )}
              </div>

              {/* Registration info */}
              {triggerReg && (
                <div className="rounded-lg border border-neutral-100 bg-neutral-50 p-3 text-xs text-neutral-500 space-y-0.5">
                  <p><span className="text-neutral-400">Registered:</span> {new Date(triggerReg.created_at).toLocaleString()}</p>
                  <p><span className="text-neutral-400">Last updated:</span> {new Date(triggerReg.updated_at).toLocaleString()}</p>
                  <p><span className="text-neutral-400">Type:</span> {triggerReg.trigger_type}</p>
                  {triggerReg.schedule && <p><span className="text-neutral-400">Schedule:</span> <code className="font-mono">{triggerReg.schedule}</code></p>}
                  {triggerReg.dedupe_window_seconds > 0 && <p><span className="text-neutral-400">Dedupe window:</span> {triggerReg.dedupe_window_seconds}s</p>}
                </div>
              )}
            </div>
          )}
        </div>
      )}
      </div>

      {/* Input Variables Modal */}
      {showVarsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="mb-1 text-base font-semibold text-neutral-900">
              {mustFillEntries.length > 0
                ? `${mustFillEntries.length} required field${mustFillEntries.length !== 1 ? "s" : ""} need input`
                : "Review Run Variables"}
            </h3>
            <p className="mb-4 text-xs text-neutral-400">
              {mustFillEntries.length > 0
                ? "Fill in the required fields. Fields with defaults are pre-filled and can be overridden below."
                : "All fields have default values. Override any before starting."}
            </p>
            <input
              value={runCaseId}
              onChange={(e) => setRunCaseId(e.target.value)}
              placeholder="Attach case_id (optional)"
              className="mb-3 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none"
            />
            <div className="max-h-[60vh] overflow-y-auto space-y-4 pr-1">
              {mustFillEntries.map(([key, meta]) => fieldRow(key, meta, false))}
              {overrideEntries.length > 0 && (
                mustFillEntries.length > 0 ? (
                  <details className="group">
                    <summary className="flex cursor-pointer select-none list-none items-center gap-1 py-2 text-xs font-medium text-neutral-500 hover:text-neutral-700">
                      <span className="inline-block transition-transform group-open:rotate-90">▶</span>
                      {`${overrideEntries.length} field${overrideEntries.length !== 1 ? "s" : ""} have defaults — expand to override`}
                    </summary>
                    <div className="space-y-4 mt-3">
                      {overrideEntries.map(([key, meta]) => fieldRow(key, meta, true))}
                    </div>
                  </details>
                ) : (
                  <div className="space-y-4">
                    {overrideEntries.map(([key, meta]) => fieldRow(key, meta, true))}
                  </div>
                )
              )}
            </div>
            <div className="mt-5 flex gap-2">
              <button
                onClick={() => {
                  const allErrors: Record<string, string> = {};
                  schemaEntries.forEach(([k, meta]) => {
                    const e = validateVarField(k, varsForm[k] ?? "", meta);
                    if (e) allErrors[k] = e;
                  });
                  if (Object.keys(allErrors).length > 0) {
                    setVarsErrors(allErrors);
                    return;
                  }
                  const parsed: Record<string, unknown> = {};
                  let parseError = false;
                  schemaEntries.forEach(([k, meta]) => {
                    const raw = varsForm[k];
                    if (meta?.type === "array" || meta?.type === "object") {
                      if (!raw) return; // blank optional field — omit
                      try { parsed[k] = JSON.parse(raw); } catch {
                        toast(`Invalid JSON for "${k}" — expected ${meta.type === "array" ? "[...]" : "{...}"}`, "error");
                        parseError = true;
                      }
                    } else {
                      parsed[k] = meta?.type === "number" ? Number(raw) : raw;
                    }
                  });
                  if (parseError) return;
                  setShowVarsModal(false);
                  void doCreateRun(parsed);
                }}
                disabled={runCreating || Object.keys(varsErrors).length > 0}
                className="flex-1 rounded-lg bg-green-600 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                {runCreating ? "Starting…" : "Start Run"}
              </button>
              <button
                onClick={() => setShowVarsModal(false)}
                className="flex-1 rounded-lg border border-neutral-300 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {showRollbackModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="mb-1 text-base font-semibold text-neutral-900">Rollback Procedure Version</h3>
            <p className="mb-4 text-xs text-neutral-500">
              Select the version to restore into {currentReleaseChannel.toUpperCase()}.
            </p>
            <div className="space-y-2">
              <label htmlFor="rollback-target-version" className="block text-xs font-medium text-neutral-700">
                Target version
              </label>
              <select
                id="rollback-target-version"
                aria-label="Rollback target version"
                value={rollbackTargetVersion}
                onChange={(e) => setRollbackTargetVersion(e.target.value)}
                className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none"
              >
                {rollbackCandidates.map((candidate) => (
                  <option key={candidate.version} value={candidate.version}>
                    v{candidate.version} ({(candidate.release_channel ?? "dev").toUpperCase()} · {candidate.status})
                  </option>
                ))}
              </select>
            </div>
            <div className="mt-5 flex gap-2">
              <button
                onClick={() => void handleRollback()}
                disabled={rollingBack || !rollbackTargetVersion}
                className="flex-1 rounded-lg bg-orange-600 py-2 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-50"
              >
                {rollingBack ? "Rolling back..." : "Confirm Rollback"}
              </button>
              <button
                onClick={() => setShowRollbackModal(false)}
                disabled={rollingBack}
                className="flex-1 rounded-lg border border-neutral-300 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete Procedure Version"
        message={procedure ? `Delete procedure ${procedure.procedure_id} v${procedure.version}? This cannot be undone.` : ""}
        confirmLabel="Delete"
        danger
        onConfirm={doDeleteVersion}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}
