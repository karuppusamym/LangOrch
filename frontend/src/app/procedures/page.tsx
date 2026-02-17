"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listProcedures, importProcedure } from "@/lib/api";
import type { Procedure } from "@/lib/types";

export default function ProceduresPage() {
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(true);
  const [showImport, setShowImport] = useState(false);
  const [importJson, setImportJson] = useState("");
  const [importError, setImportError] = useState("");

  useEffect(() => {
    loadProcedures();
  }, []);

  async function loadProcedures() {
    try {
      const data = await listProcedures();
      setProcedures(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleImport() {
    setImportError("");
    try {
      const parsed = JSON.parse(importJson);
      await importProcedure(parsed);
      setShowImport(false);
      setImportJson("");
      loadProcedures();
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Invalid JSON");
    }
  }

  return (
    <div className="space-y-6">
      {/* Actions bar */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">{procedures.length} procedure(s)</p>
        <button
          onClick={() => setShowImport(true)}
          className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
        >
          Import CKP
        </button>
      </div>

      {/* Import dialog */}
      {showImport && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold">Paste CKP JSON</h3>
          <textarea
            value={importJson}
            onChange={(e) => setImportJson(e.target.value)}
            className="h-48 w-full rounded-lg border border-gray-300 p-3 font-mono text-xs focus:border-primary-500 focus:outline-none"
            placeholder='{"procedure_id": "...", "version": "...", ...}'
          />
          {importError && <p className="mt-2 text-sm text-red-600">{importError}</p>}
          <div className="mt-3 flex gap-2">
            <button
              onClick={handleImport}
              className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
            >
              Import
            </button>
            <button
              onClick={() => { setShowImport(false); setImportError(""); }}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Procedure list */}
      {loading ? (
        <p className="text-gray-500">Loading...</p>
      ) : procedures.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 p-12 text-center text-gray-400">
          No procedures imported yet. Click &quot;Import CKP&quot; to get started.
        </div>
      ) : (
        <div className="grid gap-4">
          {procedures.map((proc) => (
            <Link
              key={`${proc.procedure_id}-${proc.version}`}
              href={`/procedures/${encodeURIComponent(proc.procedure_id)}/${encodeURIComponent(proc.version)}`}
              className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition hover:shadow-md"
            >
              <div>
                <h3 className="font-medium text-gray-900">{proc.name}</h3>
                <p className="mt-1 text-sm text-gray-500">{proc.description}</p>
                <p className="mt-1 text-xs text-gray-400">
                  {proc.procedure_id} · v{proc.version}
                </p>
              </div>
              <span className="text-xs text-gray-400">
                {new Date(proc.created_at).toLocaleDateString()}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
