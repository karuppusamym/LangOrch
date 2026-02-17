"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { createRun, deleteProcedure, getProcedure, listVersions, updateProcedure } from "@/lib/api";
import type { ProcedureDetail, Procedure } from "@/lib/types";

export default function ProcedureVersionDetailPage() {
  const params = useParams();
  const procedureId = params.id as string;
  const version = params.version as string;

  const [procedure, setProcedure] = useState<ProcedureDetail | null>(null);
  const [versions, setVersions] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(true);
  const [runStarted, setRunStarted] = useState(false);
  const [activeTab, setActiveTab] = useState<"overview" | "ckp" | "versions">("overview");
  const [editMode, setEditMode] = useState(false);
  const [ckpText, setCkpText] = useState("");

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

  async function handleStartRun() {
    if (!procedure) return;
    try {
      await createRun(procedure.procedure_id, procedure.version);
      setRunStarted(true);
    } catch (err) {
      console.error(err);
    }
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
      alert(err instanceof Error ? err.message : "Failed to save workflow");
    }
  }

  async function handleDeleteVersion() {
    if (!procedure) return;
    if (!confirm(`Delete procedure ${procedure.procedure_id} v${procedure.version}?`)) return;
    try {
      await deleteProcedure(procedure.procedure_id, procedure.version);
      window.location.href = "/procedures";
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Failed to delete workflow");
    }
  }

  if (loading) return <p className="text-gray-500">Loading procedure...</p>;
  if (!procedure) return <p className="text-red-500">Procedure not found</p>;

  const ckp = procedure.ckp_json;
  const nodes = (ckp as any)?.nodes ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <Link href="/procedures" className="text-sm text-primary-600 hover:underline">
            ← Procedures
          </Link>
          <h2 className="mt-2 text-xl font-bold text-gray-900">{procedure.name}</h2>
          <p className="mt-1 text-sm text-gray-500">{procedure.description}</p>
          <p className="mt-1 text-xs text-gray-400">
            ID: {procedure.procedure_id} · Version: {procedure.version}
          </p>
        </div>
        <button
          onClick={handleStartRun}
          disabled={runStarted}
          className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
        >
          {runStarted ? "Run Started" : "Start Run"}
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
        {(["overview", "ckp", "versions"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium ${
              activeTab === tab
                ? "border-b-2 border-primary-600 text-primary-600"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab === "ckp" ? "CKP Source" : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {activeTab === "overview" && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold text-gray-900">Workflow Nodes ({nodes.length})</h3>
          <div className="space-y-3">
            {nodes.map((node: any, i: number) => (
              <div key={node.id ?? i} className="flex items-center gap-3 rounded-lg border border-gray-100 p-3">
                <span className="badge badge-info">{node.type}</span>
                <div>
                  <p className="text-sm font-medium">{node.name ?? node.id}</p>
                  {node.description && <p className="text-xs text-gray-400">{node.description}</p>}
                </div>
              </div>
            ))}
          </div>
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
    </div>
  );
}
