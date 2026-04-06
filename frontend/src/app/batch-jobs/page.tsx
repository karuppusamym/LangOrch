"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { createBatchJob, listBatchJobs, listProcedures, listProjects } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { BatchJob, Procedure, Project } from "@/lib/types";

export default function BatchJobsPage() {
  const { toast } = useToast();
  const [jobs, setJobs] = useState<BatchJob[]>([]);
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [name, setName] = useState("");
  const [procedureRef, setProcedureRef] = useState("");
  const [sourceFormat, setSourceFormat] = useState<"json" | "jsonl" | "csv">("json");
  const [payloadText, setPayloadText] = useState("");
  const [projectId, setProjectId] = useState("");
  const [createCasePerItem, setCreateCasePerItem] = useState(false);
  const [caseType, setCaseType] = useState("");
  const [titleField, setTitleField] = useState("title");
  const [externalRefField, setExternalRefField] = useState("external_ref");

  async function load() {
    setLoading(true);
    try {
      const [jobRows, procRows, projectRows] = await Promise.all([
        listBatchJobs({ limit: 100 }),
        listProcedures(),
        listProjects(),
      ]);
      setJobs(jobRows);
      setProcedures(procRows.filter((row) => row.status !== "archived" && row.status !== "deprecated"));
      setProjects(projectRows);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load batch jobs", "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (procedureRef || procedures.length === 0) return;
    const first = procedures[0];
    if (first) setProcedureRef(`${first.procedure_id}::${first.version}`);
  }, [procedures, procedureRef]);

  const stats = useMemo(() => {
    return {
      total: jobs.length,
      running: jobs.filter((row) => row.status === "running").length,
      failed: jobs.filter((row) => row.status === "failed" || row.status === "partial_failed").length,
      completed: jobs.filter((row) => row.status === "completed").length,
    };
  }, [jobs]);

  async function handleFilePick(file: File | null) {
    if (!file) return;
    const text = await file.text();
    setPayloadText(text);
    const lower = file.name.toLowerCase();
    if (lower.endsWith(".jsonl")) setSourceFormat("jsonl");
    else if (lower.endsWith(".csv")) setSourceFormat("csv");
    else setSourceFormat("json");
  }

  async function handleSubmit() {
    const [procedureId, version] = procedureRef.split("::");
    if (!procedureId || !version) {
      toast("Select a procedure first", "warning");
      return;
    }
    if (!name.trim()) {
      toast("Batch name is required", "warning");
      return;
    }
    if (!payloadText.trim()) {
      toast("Batch payload is required", "warning");
      return;
    }
    setSubmitting(true);
    try {
      const job = await createBatchJob({
        name: name.trim(),
        procedure_id: procedureId,
        procedure_version: version,
        source_format: sourceFormat,
        payload_text: payloadText,
        project_id: projectId || null,
        create_case_per_item: createCasePerItem,
        case_type: createCasePerItem ? (caseType.trim() || null) : null,
        title_field: createCasePerItem ? (titleField.trim() || null) : null,
        external_ref_field: createCasePerItem ? (externalRefField.trim() || null) : null,
      });
      toast(`Batch created: ${job.batch_job_id.slice(0, 8)}...`, "success");
      setName("");
      setPayloadText("");
      setCreateCasePerItem(false);
      setCaseType("");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to create batch job", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] space-y-4 bg-neutral-50 p-6">
      <section className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <h1 className="text-2xl font-semibold text-neutral-900 dark:text-neutral-100">Batch Jobs</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          Submit bulk automation payloads without routing everything through cases.
        </p>
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        {[
          ["Total", String(stats.total)],
          ["Running", String(stats.running)],
          ["Completed", String(stats.completed)],
          ["Failed", String(stats.failed)],
        ].map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <p className="text-xs uppercase tracking-wide text-neutral-400">{label}</p>
            <p className="mt-2 text-2xl font-semibold text-neutral-900 dark:text-neutral-100">{value}</p>
          </div>
        ))}
      </section>

      <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Submit Batch</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Batch name" className="rounded-lg border px-3 py-2 text-sm" />
          <select value={procedureRef} onChange={(e) => setProcedureRef(e.target.value)} className="rounded-lg border px-3 py-2 text-sm">
            {procedures.map((proc) => (
              <option key={`${proc.procedure_id}::${proc.version}`} value={`${proc.procedure_id}::${proc.version}`}>
                {proc.procedure_id} v{proc.version}
              </option>
            ))}
          </select>
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="rounded-lg border px-3 py-2 text-sm">
            <option value="">Project from procedure</option>
            {projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}
          </select>
          <select value={sourceFormat} onChange={(e) => setSourceFormat(e.target.value as "json" | "jsonl" | "csv")} className="rounded-lg border px-3 py-2 text-sm">
            <option value="json">JSON array / {"{ items: [] }"}</option>
            <option value="jsonl">JSONL</option>
            <option value="csv">CSV</option>
          </select>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="inline-flex items-center gap-2 text-sm text-neutral-600">
            <input type="checkbox" checked={createCasePerItem} onChange={(e) => setCreateCasePerItem(e.target.checked)} />
            Create one case per item
          </label>
          <input type="file" accept=".json,.jsonl,.csv,.txt" onChange={(e) => void handleFilePick(e.target.files?.[0] ?? null)} className="text-xs" />
        </div>
        {createCasePerItem && (
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            <input value={caseType} onChange={(e) => setCaseType(e.target.value)} placeholder="Case type" className="rounded-lg border px-3 py-2 text-sm" />
            <input value={titleField} onChange={(e) => setTitleField(e.target.value)} placeholder="Title field name" className="rounded-lg border px-3 py-2 text-sm" />
            <input value={externalRefField} onChange={(e) => setExternalRefField(e.target.value)} placeholder="External ref field name" className="rounded-lg border px-3 py-2 text-sm" />
          </div>
        )}
        <textarea
          value={payloadText}
          onChange={(e) => setPayloadText(e.target.value)}
          placeholder='Paste JSON array, JSONL, or CSV here'
          rows={12}
          className="mt-3 w-full rounded-xl border px-3 py-2 font-mono text-sm"
        />
        <div className="mt-3 flex items-center justify-between gap-3 text-xs text-neutral-500">
          <p>For JSON, use an array of objects or an object with an `items` array.</p>
          <button onClick={() => void handleSubmit()} disabled={submitting} className="rounded-full bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            {submitting ? "Submitting..." : "Create Batch Job"}
          </button>
        </div>
      </section>

      <section className="rounded-2xl border border-neutral-200 bg-white shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="border-b border-neutral-100 px-5 py-3 text-sm font-semibold dark:border-neutral-800">Recent Batch Jobs</div>
        {loading ? (
          <div className="p-5 text-sm text-neutral-500">Loading batch jobs...</div>
        ) : jobs.length === 0 ? (
          <div className="p-5 text-sm text-neutral-500">No batch jobs yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500 dark:bg-neutral-800/50">
              <tr>
                <th className="px-4 py-3">Batch</th>
                <th className="px-4 py-3">Procedure</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Progress</th>
                <th className="px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {jobs.map((job) => (
                <tr key={job.batch_job_id}>
                  <td className="px-4 py-3">
                    <Link href={`/batch-jobs/${job.batch_job_id}`} className="font-medium text-neutral-900 hover:text-sky-700 hover:underline dark:text-neutral-100 dark:hover:text-sky-300">
                      {job.name}
                    </Link>
                    <p className="font-mono text-xs text-neutral-500">{job.batch_job_id}</p>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    <p>{job.procedure_id}</p>
                    <p className="text-neutral-500">v{job.procedure_version}</p>
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-neutral-100 px-2 py-1 text-xs dark:bg-neutral-800">{job.status}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-neutral-600">
                    {job.completed_items}/{job.total_items} completed
                    {job.failed_items > 0 ? `, ${job.failed_items} failed` : ""}
                    {job.canceled_items > 0 ? `, ${job.canceled_items} canceled` : ""}
                  </td>
                  <td className="px-4 py-3 text-xs text-neutral-500">
                    <p>{new Date(job.created_at).toLocaleString()}</p>
                    <Link href={`/runs?procedure_id=${encodeURIComponent(job.procedure_id)}`} className="text-sky-600 hover:underline">
                      View runs
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
