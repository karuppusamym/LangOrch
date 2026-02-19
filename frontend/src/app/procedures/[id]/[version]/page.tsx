"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { createRun, deleteProcedure, getGraph, getProcedure, listVersions, updateProcedure, explainProcedure } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { ProcedureDetail, Procedure, ExplainReport } from "@/lib/types";
import { ProcedureStatusBadge as StatusBadge } from "@/components/shared/ProcedureStatusBadge";

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
  { ssr: false, loading: () => <p className="text-sm text-gray-400">Loading graph...</p> }
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
  const [activeTab, setActiveTab] = useState<"overview" | "graph" | "ckp" | "versions" | "explain">(
    () => {
      const t = searchParams.get("tab");
      return (t === "graph" || t === "ckp" || t === "versions" || t === "explain") ? t : "overview";
    }
  );
  const [editMode, setEditMode] = useState(false);
  const [explainResult, setExplainResult] = useState<ExplainReport | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainError, setExplainError] = useState<string | null>(null);
  const [ckpText, setCkpText] = useState("");
  const [graphData, setGraphData] = useState<{ nodes: any[]; edges: any[] } | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [showVarsModal, setShowVarsModal] = useState(false);
  const [varsForm, setVarsForm] = useState<Record<string, string>>({});
  const [varsErrors, setVarsErrors] = useState<Record<string, string>>({});
  const [runCreating, setRunCreating] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [diffVersionA, setDiffVersionA] = useState<string>("");
  const [diffVersionB, setDiffVersionB] = useState<string>("");
  const [diffResult, setDiffResult] = useState<{ left: string; right: string; hunks: DiffHunk[] } | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const { toast } = useToast();

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

  // Auto-load graph/explain data when landing directly via ?tab=graph or ?tab=explain
  useEffect(() => {
    if (!procedure) return;
    if (activeTab === "graph" && !graphData && !graphLoading) {
      setGraphLoading(true);
      getGraph(procedure.procedure_id, procedure.version)
        .then((data) => setGraphData(data as any))
        .catch((err) => console.error("Failed to load graph:", err))
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

  const schema = (procedure?.ckp_json as any)?.variables_schema ?? {};
  const schemaEntries = Object.entries(schema) as [string, any][];

  function openStartRun() {
    if (!procedure) return;
    if (schemaEntries.length > 0) {
      const defaults: Record<string, string> = {};
      schemaEntries.forEach(([k, v]) => {
        defaults[k] = v?.default !== undefined ? String(v.default) : "";
      });
      setVarsForm(defaults);
      setVarsErrors({});
      setShowVarsModal(true);
    } else {
      void doCreateRun({});
    }
  }

  async function doCreateRun(vars: Record<string, unknown>) {
    if (!procedure) return;
    setRunCreating(true);
    try {
      const run = await createRun(procedure.procedure_id, procedure.version, vars);
      router.push(`/runs/${run.run_id}`);
    } catch (err) {
      console.error(err);
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

  if (loading) return <p className="text-gray-500">Loading procedure...</p>;
  if (!procedure) return <p className="text-red-500">Procedure not found</p>;

  const ckp = procedure.ckp_json;
  const wfNodes = (ckp as any)?.workflow_graph?.nodes ?? {};
  const nodeEntries = Object.entries(wfNodes);

  // Lazy-load graph data when tab is selected
  async function loadGraph() {
    if (graphData || graphLoading || !procedure) return;
    setGraphLoading(true);
    try {
      const data = await getGraph(procedure.procedure_id, procedure.version);
      setGraphData(data as any);
    } catch (err) {
      console.error("Failed to load graph:", err);
    } finally {
      setGraphLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <Link href="/procedures" className="text-sm text-primary-600 hover:underline">
            ← Procedures
          </Link>
          <h2 className="mt-2 text-xl font-bold text-gray-900">{procedure.name}</h2>
          <div className="mt-1 flex items-center gap-2">
            <StatusBadge status={procedure.status ?? "draft"} />
            {procedure.effective_date && (
              <span className="text-xs text-gray-400">Effective: {procedure.effective_date}</span>
            )}
          </div>
          <p className="mt-1 text-sm text-gray-500">{procedure.description}</p>
          <p className="mt-1 text-xs text-gray-400">
            ID: {procedure.procedure_id} · Version: {procedure.version}
          </p>
        </div>
        <button
          onClick={openStartRun}
          disabled={runCreating}
          className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
        >
          {runCreating ? "Starting…" : "Start Run"}
        </button>
        <button
          onClick={() => setEditMode((prev) => !prev)}
          className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          {editMode ? "Cancel Edit" : "Edit CKP"}
        </button>
        <button
          onClick={handleDeleteVersion}
          className="rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
        >
          Delete Version
        </button>
      </div>

      <div className="flex gap-1 border-b border-gray-200">
        {(["overview", "graph", "explain", "ckp", "versions"] as const).map((tab) => (
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
            }}
            className={`px-4 py-2 text-sm font-medium ${
              activeTab === tab
                ? "border-b-2 border-primary-600 text-primary-600"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab === "ckp" ? "CKP Source" : tab === "graph" ? "Workflow Graph" : tab === "explain" ? "Explain" : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {activeTab === "overview" && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold text-gray-900">Workflow Nodes ({nodeEntries.length})</h3>
          <div className="space-y-3">
            {nodeEntries.map(([nodeId, node]: [string, any]) => (
              <div key={nodeId} className="flex items-center gap-3 rounded-lg border border-gray-100 p-3">
                <span className="badge badge-info">{node.type}</span>
                <div>
                  <p className="text-sm font-medium">{nodeId}</p>
                  {node.description && <p className="text-xs text-gray-400">{node.description}</p>}
                  {node.agent && <p className="text-xs text-gray-400">Agent: {node.agent}</p>}
                </div>
              </div>
            ))}
          </div>
          {/* Provenance */}
          {procedure.provenance && (
            <div className="mt-6">
              <h4 className="mb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">Provenance</h4>
              <pre className="rounded-lg bg-gray-50 p-3 text-xs font-mono overflow-auto">
                {JSON.stringify(procedure.provenance, null, 2)}
              </pre>
            </div>
          )}
          {/* Retrieval Metadata */}
          {procedure.retrieval_metadata && (
            <div className="mt-4">
              <h4 className="mb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">Retrieval Metadata</h4>
              {Array.isArray((procedure.retrieval_metadata as any)?.tags) && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {((procedure.retrieval_metadata as any).tags as string[]).map((tag: string) => (
                    <span key={tag} className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] text-blue-700">{tag}</span>
                  ))}
                </div>
              )}
              <pre className="rounded-lg bg-gray-50 p-3 text-xs font-mono overflow-auto">
                {JSON.stringify(procedure.retrieval_metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {activeTab === "graph" && (
        <div>
          {graphLoading && <p className="text-sm text-gray-400">Loading graph...</p>}
          {graphData && <WorkflowGraph graph={graphData} />}
          {!graphLoading && !graphData && (
            <p className="text-sm text-gray-400">No graph data available.</p>
          )}
        </div>
      )}

      {activeTab === "ckp" && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          {editMode ? (
            <div className="space-y-3">
              <textarea
                value={ckpText}
                onChange={(e) => setCkpText(e.target.value)}
                title="CKP JSON editor"
                placeholder="Paste CKP JSON"
                className="h-[600px] w-full rounded-lg border border-gray-300 p-3 font-mono text-xs"
              />
              <button
                onClick={handleSaveCkp}
                className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
              >
                Save CKP
              </button>
            </div>
          ) : (
            <pre className="max-h-[600px] overflow-auto rounded-lg bg-gray-50 p-4 font-mono text-xs leading-relaxed">
              {JSON.stringify(ckp, null, 2)}
            </pre>
          )}
        </div>
      )}

      {activeTab === "explain" && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          {explainLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-400">
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
            <p className="text-sm text-gray-400">Click the Explain tab to analyse this procedure.</p>
          ) : (
            <div className="space-y-6">
              {/* Route Trace */}
              <div>
                <h4 className="mb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">Execution Route</h4>
                <div className="flex flex-wrap items-center gap-1">
                  {explainResult.route_trace.map((entry, i) => (
                    <span key={i} className="flex items-center gap-1">
                      {i > 0 && <span className="text-gray-300">→</span>}
                      <span className={`rounded px-2 py-0.5 text-xs font-mono ${
                        entry.is_terminal ? "bg-gray-100 text-gray-500" : "bg-primary-50 text-primary-700"
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
                <h4 className="mb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">Variables</h4>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <div className="rounded-lg border border-gray-100 p-3">
                    <p className="text-[10px] text-gray-500">Required</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {explainResult.variables.required.length === 0 ? <span className="text-xs text-gray-400">None</span> : explainResult.variables.required.map((v) => (
                        <span key={v} className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          explainResult.variables.provided.includes(v) ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
                        }`}>{v}</span>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-lg border border-gray-100 p-3">
                    <p className="text-[10px] text-gray-500">Produced</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {explainResult.variables.produced.length === 0 ? <span className="text-xs text-gray-400">None</span> : explainResult.variables.produced.map((v) => (
                        <span key={v} className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700">{v}</span>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-lg border border-gray-100 p-3">
                    <p className="text-[10px] text-gray-500">Missing</p>
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
                <h4 className="mb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">Nodes ({explainResult.nodes.length})</h4>
                <div className="space-y-2">
                  {explainResult.nodes.map((node) => (
                    <div key={node.id} className="rounded-lg border border-gray-100 p-3">
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold text-gray-600">{node.type}</span>
                        <span className="font-mono text-sm font-medium text-gray-900">{node.id}</span>
                        {node.agent && <span className="text-xs text-gray-400">agent: {node.agent}</span>}
                        {node.has_side_effects && <span className="rounded bg-yellow-50 px-1.5 py-0.5 text-[10px] text-yellow-600">side-effects</span>}
                        {node.is_checkpoint && <span className="rounded bg-teal-50 px-1.5 py-0.5 text-[10px] text-teal-600">checkpoint</span>}
                        {node.timeout_ms && <span className="text-[10px] text-gray-400">timeout: {node.timeout_ms}ms</span>}
                      </div>
                      {node.description && <p className="mt-1 text-xs text-gray-500">{node.description}</p>}
                      {node.sla && <p className="mt-1 text-[10px] text-orange-500">SLA: {JSON.stringify(node.sla)}</p>}
                      {node.steps.length > 0 && (
                        <div className="mt-2 border-t border-gray-50 pt-2">
                          <p className="text-[10px] text-gray-400 mb-1">Steps:</p>
                          <div className="flex flex-wrap gap-1">
                            {node.steps.map((s) => (
                              <span key={s.step_id} className="rounded bg-gray-50 px-1.5 py-0.5 text-[10px] text-gray-600">{s.step_id}: {s.action}{s.binding_kind ? ` [${s.binding_kind}]` : ""}</span>
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
                  <h4 className="mb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">External Calls ({explainResult.external_calls.length})</h4>
                  <div className="overflow-auto">
                    <table className="w-full text-xs">
                      <thead><tr className="border-b text-left text-gray-500"><th className="pb-1 pr-3">Node</th><th className="pb-1 pr-3">Step</th><th className="pb-1 pr-3">Action</th><th className="pb-1 pr-3">Binding</th><th className="pb-1">Ref</th></tr></thead>
                      <tbody>
                        {explainResult.external_calls.map((call, i) => (
                          <tr key={i} className="border-b last:border-0">
                            <td className="py-1 pr-3 font-mono">{call.node_id}</td>
                            <td className="py-1 pr-3 font-mono">{call.step_id ?? "—"}</td>
                            <td className="py-1 pr-3">{call.action}</td>
                            <td className="py-1 pr-3"><span className="rounded bg-blue-50 px-1 text-blue-600">{call.binding_kind}</span></td>
                            <td className="py-1 font-mono text-gray-500">{call.binding_ref ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Edges */}
              <div>
                <h4 className="mb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">Edges ({explainResult.edges.length})</h4>
                <div className="flex flex-wrap gap-1">
                  {explainResult.edges.map((edge, i) => (
                    <span key={i} className="rounded bg-gray-50 px-2 py-0.5 text-[10px] text-gray-600">
                      {edge.from} → {edge.to}{edge.condition ? ` [${edge.condition}]` : ""}
                    </span>
                  ))}
                </div>
              </div>

              {/* Policy Summary */}
              {Object.keys(explainResult.policy_summary).length > 0 && (
                <div>
                  <h4 className="mb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">Policy Summary</h4>
                  <pre className="rounded-lg bg-gray-50 p-3 font-mono text-xs">{JSON.stringify(explainResult.policy_summary, null, 2)}</pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {activeTab === "versions" && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          {versions.length === 0 ? (
            <p className="text-sm text-gray-400">No other versions</p>
          ) : (
            <div className="space-y-4">
              {/* Version list */}
              <div className="space-y-2">
                {versions.map((v) => (
                  <div key={v.version} className="flex items-center justify-between rounded-lg border border-gray-100 p-3">
                    <Link
                      href={`/procedures/${encodeURIComponent(v.procedure_id)}/${encodeURIComponent(v.version)}`}
                      className={`text-sm font-medium ${v.version === version ? "text-primary-600 font-bold" : "text-gray-700 hover:text-primary-600"}`}
                    >
                      v{v.version} {v.version === version && "(current)"}
                    </Link>
                    <span className="text-xs text-gray-400">{new Date(v.created_at).toLocaleString()}</span>
                  </div>
                ))}
              </div>

              {/* Diff Comparison */}
              {versions.length >= 2 && (
                <div className="border-t border-gray-200 pt-4">
                  <h4 className="mb-3 text-sm font-semibold text-gray-900">Compare Versions</h4>
                  <div className="flex flex-wrap items-center gap-3 mb-3">
                    <select
                      value={diffVersionA}
                      onChange={(e) => setDiffVersionA(e.target.value)}
                      className="rounded-md border border-gray-300 px-2 py-1 text-xs"
                    >
                      <option value="">Base version…</option>
                      {versions.map((v) => (<option key={v.version} value={v.version}>v{v.version}</option>))}
                    </select>
                    <span className="text-xs text-gray-400">vs</span>
                    <select
                      value={diffVersionB}
                      onChange={(e) => setDiffVersionB(e.target.value)}
                      className="rounded-md border border-gray-300 px-2 py-1 text-xs"
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
                      className="rounded-md bg-primary-600 px-3 py-1 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                    >
                      {diffLoading ? "Loading…" : "Compare"}
                    </button>
                  </div>

                  {/* Diff output */}
                  {diffResult && (
                    <div className="rounded-lg border border-gray-200 overflow-auto max-h-[600px]">
                      <table className="w-full font-mono text-xs">
                        <thead>
                          <tr className="border-b bg-gray-50 text-gray-500">
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
                              <td className="px-2 py-0.5 text-right text-gray-400 select-none border-r border-gray-100">
                                {h.lineA ?? ""}
                              </td>
                              <td className="px-2 py-0.5 text-right text-gray-400 select-none border-r border-gray-100">
                                {h.lineB ?? ""}
                              </td>
                              <td className="px-3 py-0.5 whitespace-pre">
                                <span className={
                                  h.type === "added"
                                    ? "text-green-700"
                                    : h.type === "removed"
                                    ? "text-red-700"
                                    : "text-gray-700"
                                }>
                                  {h.type === "added" ? "+ " : h.type === "removed" ? "- " : "  "}{h.text}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <div className="border-t border-gray-200 bg-gray-50 px-3 py-2 flex items-center gap-4 text-xs text-gray-500">
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
      {/* Input Variables Modal */}
      {showVarsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <h3 className="mb-4 text-base font-semibold text-gray-900">Set Input Variables</h3>
            <div className="max-h-[60vh] overflow-y-auto space-y-4 pr-1">
              {schemaEntries.map(([key, meta]) => {
                const validation = (meta?.validation ?? {}) as Record<string, any>;
                const allowed = validation.allowed_values as string[] | undefined;
                const isRequired = !!meta?.required;
                const fieldErr = varsErrors[key];
                const borderCls = fieldErr
                  ? "border-red-400 focus:border-red-500"
                  : "border-gray-300 focus:border-primary-500";
                return (
                  <div key={key}>
                    <label className="mb-1 block text-xs font-medium text-gray-600">
                      {key}
                      {meta?.type && <span className="ml-1 text-gray-400">({meta.type})</span>}
                      {isRequired && <span className="ml-1 text-red-500">*</span>}
                    </label>
                    {meta?.description && (
                      <p className="mb-1 text-xs text-gray-400">{meta.description}</p>
                    )}
                    {allowed ? (
                      <select
                        value={varsForm[key] ?? ""}
                        onChange={(e) => handleVarChange(key, e.target.value, meta)}
                        className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}
                      >
                        <option value="">— select —</option>
                        {allowed.map((v: string) => (
                          <option key={v} value={v}>{v}</option>
                        ))}
                      </select>
                    ) : meta?.type === "array" || meta?.type === "object" ? (
                      <textarea
                        value={varsForm[key] ?? ""}
                        onChange={(e) => handleVarChange(key, e.target.value, meta)}
                        placeholder={meta?.type === "array" ? '["item1","item2"]' : '{"key":"value"}'}
                        rows={3}
                        className={`w-full rounded-lg border p-2 text-sm focus:outline-none font-mono ${borderCls}`}
                      />
                    ) : (
                      <input
                        type={meta?.type === "number" ? "number" : "text"}
                        value={varsForm[key] ?? ""}
                        onChange={(e) => handleVarChange(key, e.target.value, meta)}
                        placeholder={meta?.default !== undefined ? String(meta.default) : ""}
                        className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}
                      />
                    )}
                    {fieldErr ? (
                      <p className="mt-1 text-xs text-red-500">{fieldErr}</p>
                    ) : (
                      <span className="mt-1 inline-flex gap-3">
                        {validation.regex && (
                          <span className="text-xs text-gray-400">
                            Pattern: <code className="font-mono">{validation.regex as string}</code>
                          </span>
                        )}
                        {validation.min !== undefined && (
                          <span className="text-xs text-gray-400">Min: {validation.min as number}</span>
                        )}
                        {validation.max !== undefined && (
                          <span className="text-xs text-gray-400">Max: {validation.max as number}</span>
                        )}
                      </span>
                    )}
                  </div>
                );
              })}
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
                      try { parsed[k] = JSON.parse(raw ?? "null"); } catch {
                        toast(`Invalid JSON for "${k}"`, "error");
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
                className="flex-1 rounded-lg border border-gray-300 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
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
