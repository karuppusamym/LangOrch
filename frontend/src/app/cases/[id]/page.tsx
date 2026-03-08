"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  claimCase,
  createRun,
  getCase,
  getProcedure,
  isNotFoundError,
  listCaseEvents,
  listProcedures,
  listRuns,
  releaseCase,
  updateCase,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { flattenVariablesSchema, isFieldSensitive } from "@/lib/redact";
import type { Case, CaseEvent, Procedure, Run } from "@/lib/types";
import type { ProcedureDetail } from "@/lib/types";

const STATUS_OPTIONS = ["open", "in_progress", "resolved", "closed", "escalated"];
const PRIORITY_OPTIONS = ["urgent", "high", "normal", "low"];

function fmtDate(value: string | null | undefined) {
  if (!value) return "-";
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? value : dt.toLocaleString();
}

export default function CaseDetailPage() {
  const params = useParams();
  const caseId = params.id as string;
  const { toast } = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [caseItem, setCaseItem] = useState<Case | null>(null);
  const [events, setEvents] = useState<CaseEvent[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [claimOwner, setClaimOwner] = useState("");
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [runProcedureRef, setRunProcedureRef] = useState("");
  const [runModalOpen, setRunModalOpen] = useState(false);
  const [runModalProcedure, setRunModalProcedure] = useState<ProcedureDetail | null>(null);
  const [runVarsForm, setRunVarsForm] = useState<Record<string, string>>({});
  const [runVarsErrors, setRunVarsErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    void load();
  }, [caseId]);

  useEffect(() => {
    void listProcedures().then(setProcedures).catch(() => null);
  }, []);

  async function load() {
    setLoading(true);
    try {
      const [caseData, caseEvents, caseRuns] = await Promise.all([
        getCase(caseId),
        listCaseEvents(caseId, 300),
        listRuns({ case_id: caseId, limit: 200, order: "desc" }),
      ]);
      setCaseItem(caseData);
      setEvents(caseEvents);
      setRuns(caseRuns);
      if (caseData.owner) setClaimOwner(caseData.owner);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load case", "error");
    } finally {
      setLoading(false);
    }
  }

  async function patchCase(patch: Record<string, unknown>) {
    if (!caseItem) return;
    setSaving(true);
    try {
      await updateCase(caseItem.case_id, patch);
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to update case", "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleClaim() {
    if (!caseItem) return;
    if (!claimOwner.trim()) return toast("Owner is required to claim", "warning");
    setSaving(true);
    try {
      await claimCase(caseItem.case_id, claimOwner.trim(), true);
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to claim case", "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleRelease() {
    if (!caseItem) return;
    setSaving(true);
    try {
      await releaseCase(caseItem.case_id, caseItem.owner ?? undefined, true);
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to release case", "error");
    } finally {
      setSaving(false);
    }
  }

  const launchableProcedures = procedures.filter((p) => {
    if (p.status === "archived" || p.status === "deprecated") return false;
    if (!caseItem?.project_id) return true;
    return p.project_id === caseItem.project_id;
  });

  useEffect(() => {
    if (launchableProcedures.length === 0) {
      setRunProcedureRef("");
      return;
    }
    if (!launchableProcedures.some((p) => `${p.procedure_id}::${p.version}` === runProcedureRef)) {
      const first = launchableProcedures[0];
      setRunProcedureRef(`${first.procedure_id}::${first.version}`);
    }
  }, [launchableProcedures, runProcedureRef]);

  const runModalSchema = flattenVariablesSchema(
    ((runModalProcedure?.ckp_json as any)?.variables_schema ?? {}) as Record<string, unknown>
  );
  const runModalSchemaEntries = Object.entries(runModalSchema) as [string, any][];
  const runModalMustFillEntries = runModalSchemaEntries.filter(([, meta]) => !!meta?.required && meta?.default === undefined);
  const runModalOverrideEntries = runModalSchemaEntries.filter(([, meta]) => !meta?.required || meta?.default !== undefined);

  function validateVarField(key: string, raw: string, meta: Record<string, any>): string {
    const validation = (meta?.validation ?? {}) as Record<string, any>;
    const vtype = (meta?.type ?? "string") as string;
    if (meta?.required && !raw.trim()) return "This field is required";
    if (!raw) return "";
    if (validation.regex) {
      try {
        if (!new RegExp(`^(?:${validation.regex as string})$`).test(raw)) {
          return `Must match pattern: ${validation.regex as string}`;
        }
      } catch {
        // ignore malformed schema regex
      }
    }
    if (vtype === "number") {
      const num = Number(raw);
      if (validation.min !== undefined && num < (validation.min as number)) return `Minimum value is ${validation.min as number}`;
      if (validation.max !== undefined && num > (validation.max as number)) return `Maximum value is ${validation.max as number}`;
    }
    const allowed = validation.allowed_values as string[] | undefined;
    if (allowed && !allowed.includes(raw)) return `Must be one of: ${allowed.join(", ")}`;
    return "";
  }

  function handleRunVarChange(key: string, raw: string, meta: Record<string, any>) {
    setRunVarsForm((prev) => ({ ...prev, [key]: raw }));
    const err = validateVarField(key, raw, meta);
    setRunVarsErrors((prev) => {
      const next = { ...prev };
      if (err) next[key] = err;
      else delete next[key];
      return next;
    });
  }

  function runFieldRow(key: string, meta: Record<string, any>, showDefault = false) {
    const validation = (meta?.validation ?? {}) as Record<string, any>;
    const allowed = validation.allowed_values as string[] | undefined;
    const isRequired = !!meta?.required;
    const hasDefault = meta?.default !== undefined;
    const sensitive = isFieldSensitive(meta as Record<string, unknown>);
    const currentVal = runVarsForm[key] ?? "";
    const isUsingDefault = hasDefault && currentVal === String(meta.default);
    const fieldErr = runVarsErrors[key];
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
          {sensitive && <span className="text-[10px] font-medium text-yellow-600">sensitive</span>}
          {showDefault && hasDefault && !sensitive && (
            <span className="ml-auto text-[10px] text-gray-400">
              default: <code className="font-mono">{String(meta.default)}</code>
              {!isUsingDefault && (
                <button
                  type="button"
                  onClick={() => handleRunVarChange(key, String(meta.default), meta)}
                  className="ml-1 text-primary-600 hover:underline"
                >
                  restore
                </button>
              )}
            </span>
          )}
        </div>
        {meta?.description && <p className="mb-1.5 text-xs text-gray-400">{meta.description as string}</p>}
        {allowed ? (
          <select
            aria-label={key}
            value={currentVal}
            onChange={(e) => handleRunVarChange(key, e.target.value, meta)}
            className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}
          >
            <option value="">- select -</option>
            {allowed.map((v: string) => <option key={v} value={v}>{v}</option>)}
          </select>
        ) : meta?.type === "array" || meta?.type === "object" ? (
          <textarea
            value={currentVal}
            onChange={(e) => handleRunVarChange(key, e.target.value, meta)}
            placeholder={meta?.type === "array" ? '["item1","item2"]' : '{"key":"value"}'}
            rows={3}
            className={`w-full rounded-lg border p-2 font-mono text-sm focus:outline-none ${borderCls}`}
          />
        ) : (
          <input
            type={sensitive ? "password" : meta?.type === "number" ? "number" : "text"}
            value={currentVal}
            onChange={(e) => handleRunVarChange(key, e.target.value, meta)}
            placeholder={hasDefault && !sensitive ? String(meta.default) : ""}
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

  async function handleStartRun() {
    if (!caseItem) return;
    if (!runProcedureRef) return toast("Select a procedure", "warning");
    const [procedureId, version] = runProcedureRef.split("::");
    if (!procedureId || !version) return toast("Invalid procedure selection", "error");
    try {
      const detail = await getProcedure(procedureId, version);
      const schema = flattenVariablesSchema(((detail.ckp_json as any)?.variables_schema ?? {}) as Record<string, unknown>);
      const defaults: Record<string, string> = {};
      for (const [key, meta] of Object.entries(schema)) {
        defaults[key] = (meta as any)?.default !== undefined ? String((meta as any).default) : "";
      }
      setRunVarsForm(defaults);
      setRunVarsErrors({});
      setRunModalProcedure(detail);
      setRunModalOpen(true);
    } catch (err) {
      if (isNotFoundError(err)) {
        toast("Selected procedure version is no longer available.", "error");
        return;
      }
      toast(err instanceof Error ? err.message : "Failed to prepare run", "error");
    }
  }

  async function submitCaseRun() {
    if (!caseItem || !runModalProcedure) return;
    const allErrors: Record<string, string> = {};
    runModalSchemaEntries.forEach(([k, meta]) => {
      const e = validateVarField(k, runVarsForm[k] ?? "", meta);
      if (e) allErrors[k] = e;
    });
    if (Object.keys(allErrors).length > 0) {
      setRunVarsErrors(allErrors);
      return;
    }

    const parsed: Record<string, unknown> = {};
    let parseError = false;
    runModalSchemaEntries.forEach(([k, meta]) => {
      const raw = runVarsForm[k];
      if (meta?.type === "array" || meta?.type === "object") {
        if (!raw) return;
        try {
          parsed[k] = JSON.parse(raw);
        } catch {
          toast(`Invalid JSON for "${k}"`, "error");
          parseError = true;
        }
      } else {
        parsed[k] = meta?.type === "number" ? Number(raw) : raw;
      }
    });
    if (parseError) return;

    setSaving(true);
    try {
      // Verify case still exists before creating run
      try {
        await getCase(caseItem.case_id);
      } catch {
        toast("Case no longer exists. Please refresh the page.", "error");
        await load();
        setSaving(false);
        return;
      }

      await createRun(
        runModalProcedure.procedure_id,
        runModalProcedure.version,
        parsed,
        { case_id: caseItem.case_id, project_id: caseItem.project_id ?? undefined }
      );
      toast("Run started for case", "success");
      setRunModalOpen(false);
      await load();
    } catch (err) {
      if (isNotFoundError(err)) {
        toast("Case not found. It may have been deleted.", "error");
        await load();
      } else {
        toast(err instanceof Error ? err.message : "Failed to start run", "error");
      }
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="p-6 text-sm text-neutral-500">Loading case...</div>;
  if (!caseItem) return <div className="p-6 text-sm text-red-600">Case not found</div>;

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Link href="/cases" className="text-sm text-blue-600 hover:underline">← Cases</Link>
          <h1 className="mt-1 text-2xl font-bold text-neutral-900 dark:text-neutral-100">{caseItem.title}</h1>
          <p className="font-mono text-xs text-neutral-500">{caseItem.case_id}</p>
        </div>
        <button onClick={() => void load()} className="rounded-lg border px-3 py-1.5 text-sm">Refresh</button>
      </div>

      <div className="grid gap-3 lg:grid-cols-[1fr_1fr_1.2fr]">
        <div className="rounded-xl border bg-white dark:bg-neutral-900 p-4 space-y-2 text-sm">
          <h2 className="font-semibold">Case State</h2>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-neutral-500">Status</label>
            <select
              aria-label="Case status"
              value={caseItem.status}
              disabled={saving}
              onChange={(e) => void patchCase({ status: e.target.value })}
              className="rounded border px-2 py-1 text-xs"
            >
              {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
            <label className="text-xs text-neutral-500">Priority</label>
            <select
              aria-label="Case priority"
              value={caseItem.priority}
              disabled={saving}
              onChange={(e) => void patchCase({ priority: e.target.value })}
              className="rounded border px-2 py-1 text-xs"
            >
              {PRIORITY_OPTIONS.map((priority) => <option key={priority} value={priority}>{priority}</option>)}
            </select>
            <label className="text-xs text-neutral-500">Owner</label>
            <input
              value={claimOwner}
              onChange={(e) => setClaimOwner(e.target.value)}
              placeholder="owner"
              className="rounded border px-2 py-1 text-xs"
            />
          </div>
          <div className="flex gap-2 pt-1">
            <button onClick={() => void handleClaim()} disabled={saving} className="rounded border px-2 py-1 text-xs">Claim</button>
            <button onClick={() => void handleRelease()} disabled={saving || !caseItem.owner} className="rounded border px-2 py-1 text-xs">Release</button>
          </div>
        </div>

        <div className="rounded-xl border bg-white dark:bg-neutral-900 p-4 space-y-1 text-xs">
          <h2 className="mb-2 text-sm font-semibold">Case Metadata</h2>
          <p><span className="text-neutral-500">Project:</span> {caseItem.project_id ?? "-"}</p>
          <p><span className="text-neutral-500">Type:</span> {caseItem.case_type ?? "-"}</p>
          <p><span className="text-neutral-500">External Ref:</span> {caseItem.external_ref ?? "-"}</p>
          <p><span className="text-neutral-500">Owner:</span> {caseItem.owner ?? "-"}</p>
          <p><span className="text-neutral-500">SLA Due:</span> {fmtDate(caseItem.sla_due_at)}</p>
          <p><span className="text-neutral-500">SLA Breached:</span> {fmtDate(caseItem.sla_breached_at)}</p>
          <p><span className="text-neutral-500">Created:</span> {fmtDate(caseItem.created_at)}</p>
          <p><span className="text-neutral-500">Updated:</span> {fmtDate(caseItem.updated_at)}</p>
        </div>

        <div className="rounded-xl border bg-white dark:bg-neutral-900 p-4">
          <h2 className="mb-2 text-sm font-semibold">Linked Runs ({runs.length})</h2>
          <div className="mb-3 space-y-2 rounded border border-neutral-200 dark:border-neutral-800 p-2">
            <p className="text-xs text-neutral-500">Start run for this case</p>
            <select
              aria-label="Select procedure for case run"
              value={runProcedureRef}
              onChange={(e) => setRunProcedureRef(e.target.value)}
              className="w-full rounded border px-2 py-1 text-xs"
            >
              {launchableProcedures.length === 0 ? (
                <option value="">No procedures available</option>
              ) : (
                launchableProcedures.map((proc) => (
                  <option key={`${proc.procedure_id}:${proc.version}`} value={`${proc.procedure_id}::${proc.version}`}>
                    {proc.name} ({proc.procedure_id} v{proc.version})
                  </option>
                ))
              )}
            </select>
            <button
              onClick={() => void handleStartRun()}
              disabled={saving || launchableProcedures.length === 0}
              className="w-full rounded border border-blue-300 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-blue-900 dark:bg-blue-950/20 dark:text-blue-300"
            >
              Start Run
            </button>
          </div>
          <div className="max-h-48 space-y-1 overflow-y-auto">
            {runs.length === 0 ? (
              <p className="text-xs text-neutral-500">No runs linked to this case.</p>
            ) : runs.map((run) => (
              <Link
                key={run.run_id}
                href={`/runs/${run.run_id}`}
                className="block rounded border px-2 py-1 text-xs hover:bg-neutral-50 dark:hover:bg-neutral-800"
              >
                <p className="font-mono text-blue-600">{run.run_id}</p>
                <p className="text-neutral-500">{run.procedure_id} ({run.status})</p>
              </Link>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-xl border bg-white dark:bg-neutral-900 p-4">
        <h2 className="mb-2 text-sm font-semibold">Timeline ({events.length})</h2>
        <div className="max-h-[28rem] space-y-2 overflow-y-auto">
          {events.length === 0 ? (
            <p className="text-xs text-neutral-500">No case events recorded yet.</p>
          ) : events.map((event) => (
            <div key={event.event_id} className="rounded border px-3 py-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium">{event.event_type}</p>
                <p className="text-neutral-500">{fmtDate(event.ts)}</p>
              </div>
              <p className="text-neutral-500">actor: {event.actor ?? "-"}</p>
              {event.payload && (
                <pre className="mt-1 overflow-auto rounded bg-neutral-50 dark:bg-neutral-800 p-2 text-[11px]">
                  {JSON.stringify(event.payload, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      </div>

      {runModalOpen && runModalProcedure && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <h3 className="mb-0.5 text-base font-semibold text-gray-900">
              {runModalMustFillEntries.length > 0
                ? `${runModalMustFillEntries.length} required field${runModalMustFillEntries.length !== 1 ? "s" : ""} need input`
                : "Review Run Variables"}
            </h3>
            <p className="mb-1 text-xs font-medium text-gray-500">{runModalProcedure.name}</p>
            <p className="mb-4 text-xs text-gray-400">
              {runModalMustFillEntries.length > 0
                ? "Fill in the required fields before starting."
                : "All fields have default values. Override any before starting."}
            </p>
            <div className="mb-3 rounded border border-blue-100 bg-blue-50 p-2 text-xs text-blue-700">
              Starting for case: <span className="font-mono">{caseItem.case_id}</span>
            </div>
            <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
              {runModalMustFillEntries.map(([key, meta]) => runFieldRow(key, meta, false))}
              {runModalOverrideEntries.length > 0 && (
                runModalMustFillEntries.length > 0 ? (
                  <details className="group">
                    <summary className="flex list-none cursor-pointer select-none items-center gap-1 py-2 text-xs font-medium text-gray-500 hover:text-gray-700">
                      <span className="inline-block transition-transform group-open:rotate-90">▶</span>
                      {`${runModalOverrideEntries.length} field${runModalOverrideEntries.length !== 1 ? "s" : ""} have defaults - expand to override`}
                    </summary>
                    <div className="mt-3 space-y-4">
                      {runModalOverrideEntries.map(([key, meta]) => runFieldRow(key, meta, true))}
                    </div>
                  </details>
                ) : (
                  <div className="space-y-4">
                    {runModalOverrideEntries.map(([key, meta]) => runFieldRow(key, meta, true))}
                  </div>
                )
              )}
            </div>
            <div className="mt-5 flex gap-2">
              <button
                onClick={() => void submitCaseRun()}
                disabled={saving || Object.keys(runVarsErrors).length > 0}
                className="flex-1 rounded-lg bg-green-600 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                {saving ? "Starting..." : "Start Run"}
              </button>
              <button
                onClick={() => setRunModalOpen(false)}
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
