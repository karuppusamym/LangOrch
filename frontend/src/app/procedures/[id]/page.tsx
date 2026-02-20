"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { getProcedure, createRun, getGraph, listVersions, listRuns } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ProcedureStatusBadge as StatusBadge } from "@/components/shared/ProcedureStatusBadge";
import type { ProcedureDetail, Procedure, Run } from "@/lib/types";

const WorkflowGraph = dynamic(
  () => import("@/components/WorkflowGraphWrapper"),
  { ssr: false, loading: () => <p className="text-sm text-gray-400">Loading graph...</p> }
);

export default function ProcedureDetailPage() {
  const params = useParams();
  const router = useRouter();
  const procedureId = params.id as string;

  const [procedure, setProcedure] = useState<ProcedureDetail | null>(null);
  const [versions, setVersions] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"overview" | "graph" | "ckp" | "versions" | "runs">("overview");
  const [graphData, setGraphData] = useState<{ nodes: any[]; edges: any[] } | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [procedureRuns, setProcedureRuns] = useState<Run[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [showVarsModal, setShowVarsModal] = useState(false);
  const [varsForm, setVarsForm] = useState<Record<string, string>>({});
  const [varsErrors, setVarsErrors] = useState<Record<string, string>>({});
  const [runCreating, setRunCreating] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    async function load() {
      try {
        const vers = await listVersions(procedureId);
        setVersions(vers);
        if (vers.length > 0) {
          const proc = await getProcedure(procedureId, vers[0].version);
          setProcedure(proc);
        }
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [procedureId]);

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
    const isSensitive = !!(meta?.sensitive) || meta?.type === "password";
    const currentVal = varsForm[key] ?? "";
    const isUsingDefault = hasDefault && currentVal === String(meta.default);
    const fieldErr = varsErrors[key];
    const borderCls = fieldErr
      ? "border-red-400 focus:border-red-500"
      : showDefault && isUsingDefault
      ? "border-gray-200 bg-gray-50 focus:border-primary-500 focus:bg-white"
      : "border-gray-300 focus:border-primary-500";
    return (
      <div key={key}>
        <div className="mb-1 flex flex-wrap items-baseline gap-x-2">
          <label className="text-xs font-semibold text-gray-700">
            {key}{isRequired && <span className="ml-0.5 text-red-500">*</span>}
          </label>
          {meta?.type && <span className="text-[10px] uppercase tracking-wide text-gray-400">{meta.type as string}</span>}
          {isSensitive && <span className="text-[10px] text-yellow-600 font-medium">🔒 sensitive</span>}
          {showDefault && hasDefault && !isSensitive && (
            <span className="ml-auto text-[10px] text-gray-400">
              default: <code className="font-mono">{String(meta.default)}</code>
              {!isUsingDefault && (
                <button type="button" onClick={() => handleVarChange(key, String(meta.default), meta)} className="ml-1 text-primary-600 hover:underline">restore</button>
              )}
            </span>
          )}
        </div>
        {meta?.description && <p className="mb-1.5 text-xs text-gray-400">{meta.description as string}</p>}
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
            {validation.regex && <span className="text-xs text-gray-400">Pattern: <code className="font-mono">{validation.regex as string}</code></span>}
            {validation.min !== undefined && <span className="text-xs text-gray-400">Min: {validation.min as number}</span>}
            {validation.max !== undefined && <span className="text-xs text-gray-400">Max: {validation.max as number}</span>}
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
    // Always show the modal when the schema has any variables so the user can
    // review / override values (even if all have defaults).
    if (schemaEntries.length > 0) {
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

  if (loading) return <p className="text-gray-500">Loading procedure...</p>;
  if (!procedure) return <p className="text-red-500">Procedure not found</p>;

  const ckp = procedure.ckp_json;
  const wfNodes = (ckp as any)?.workflow_graph?.nodes ?? {};
  const nodeEntries = Object.entries(wfNodes);

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
      {/* Header */}
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
          title={procedure.status === "draft" ? "This procedure is in DRAFT status" : undefined}
          className={`rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50 ${
            procedure.status === "draft"
              ? "bg-green-600 hover:bg-green-700 ring-2 ring-amber-400 ring-offset-1"
              : "bg-green-600 hover:bg-green-700"
          }`}
        >
          {runCreating ? "Starting\u2026" : procedure.status === "draft" ? "Start Run (draft)" : "Start Run"}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {(["overview", "graph", "ckp", "versions", "runs"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => {
              setActiveTab(tab);
              if (tab === "graph") loadGraph();
              if (tab === "runs" && procedureRuns.length === 0 && !runsLoading) {
                setRunsLoading(true);
                listRuns({ procedure_id: procedureId })
                  .then(setProcedureRuns)
                  .catch(console.error)
                  .finally(() => setRunsLoading(false));
              }
            }}
            className={`px-4 py-2 text-sm font-medium ${
              activeTab === tab
                ? "border-b-2 border-primary-600 text-primary-600"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab === "ckp" ? "CKP Source" : tab === "graph" ? "Workflow Graph" : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab content */}
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
          <pre className="max-h-[600px] overflow-auto rounded-lg bg-gray-50 p-4 font-mono text-xs leading-relaxed">
            {JSON.stringify(ckp, null, 2)}
          </pre>
        </div>
      )}

      {activeTab === "versions" && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          {versions.length === 0 ? (
            <p className="text-sm text-gray-400">No other versions</p>
          ) : (
            <div className="space-y-2">
              {versions.map((v) => (
                <Link
                  key={v.version}
                  href={`/procedures/${encodeURIComponent(v.procedure_id)}/${encodeURIComponent(v.version)}`}
                  className="flex items-center justify-between rounded-lg border border-gray-100 p-3"
                >
                  <span className="text-sm font-medium">v{v.version}</span>
                  <span className="text-xs text-gray-400">{new Date(v.created_at).toLocaleString()}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
      {/* Input Variables Modal */}
      {showVarsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <h3 className="mb-1 text-base font-semibold text-gray-900">
              {mustFillEntries.length > 0
                ? `${mustFillEntries.length} required field${mustFillEntries.length !== 1 ? "s" : ""} need input`
                : "Review Run Variables"}
            </h3>
            <p className="mb-4 text-xs text-gray-400">
              {mustFillEntries.length > 0
                ? "Fill in the required fields. Fields with defaults are pre-filled and can be overridden below."
                : "All fields have default values. Override any before starting."}
            </p>
            <div className="max-h-[60vh] overflow-y-auto space-y-4 pr-1">
              {mustFillEntries.map(([key, meta]) => fieldRow(key, meta, false))}
              {overrideEntries.length > 0 && (
                mustFillEntries.length > 0 ? (
                  <details className="group">
                    <summary className="flex cursor-pointer select-none list-none items-center gap-1 py-2 text-xs font-medium text-gray-500 hover:text-gray-700">
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
                className="flex-1 rounded-lg border border-gray-300 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
