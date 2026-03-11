import { useState } from "react";

import type { ExplainReport } from "@/lib/types";

type BuilderIssue = { nodeId?: string; message: string };

interface BuilderWorkspacePanelsProps {
  validation: { errors: BuilderIssue[]; warnings: BuilderIssue[] };
  compilePreviewLoading: boolean;
  compilePreviewError: string | null;
  compilePreview: ExplainReport | null;
  previewJson: string;
  isOpen: boolean;
  onToggleOpen: () => void;
  onSelectNode: (nodeId: string | null) => void;
}

export function BuilderWorkspacePanels({
  validation,
  compilePreviewLoading,
  compilePreviewError,
  compilePreview,
  previewJson,
  isOpen,
  onToggleOpen,
  onSelectNode,
}: BuilderWorkspacePanelsProps) {
  const [activePanel, setActivePanel] = useState<"validation" | "preview">("validation");

  return (
    <div className="flex h-full min-h-0 flex-col border-t border-neutral-200 bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-neutral-200 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
          <span className="font-bold uppercase tracking-widest text-neutral-400">Workspace Panels</span>
          <span className={`rounded-full px-2.5 py-1 ${validation.errors.length > 0 ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"}`}>
            {validation.errors.length} errors
          </span>
          <span className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-700">
            {validation.warnings.length} warnings
          </span>
          {compilePreview ? (
            <span className="rounded-full bg-sky-100 px-2.5 py-1 text-sky-700">
              preview ready
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-xl border border-neutral-200 bg-neutral-50 p-1">
            <button
              type="button"
              onClick={() => setActivePanel("validation")}
              className={activePanel === "validation"
                ? "rounded-lg bg-white px-2.5 py-1 text-[11px] font-medium text-neutral-800 shadow-sm"
                : "rounded-lg px-2.5 py-1 text-[11px] font-medium text-neutral-500 hover:bg-white/70"}
            >
              Validation
            </button>
            <button
              type="button"
              onClick={() => setActivePanel("preview")}
              className={activePanel === "preview"
                ? "rounded-lg bg-white px-2.5 py-1 text-[11px] font-medium text-neutral-800 shadow-sm"
                : "rounded-lg px-2.5 py-1 text-[11px] font-medium text-neutral-500 hover:bg-white/70"}
            >
              CKP Preview
            </button>
          </div>
          <button
            type="button"
            onClick={onToggleOpen}
            className="rounded-xl border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50"
          >
            {isOpen ? "Collapse Panels" : "Expand Panels"}
          </button>
        </div>
      </div>

      {isOpen ? (
        <div className="min-h-0 flex-1 overflow-auto bg-white p-4">
          {activePanel === "validation" ? (
          <section>
            <div className="mb-3 flex items-center justify-between gap-2">
              <p className="text-xs font-bold uppercase tracking-widest text-neutral-400">Validation</p>
            </div>
            <div className="space-y-2">
              {validation.errors.map((issue, index) => (
                <button
                  key={`full-error-${index}`}
                  type="button"
                  onClick={() => onSelectNode(issue.nodeId ?? null)}
                  className="block w-full rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-left text-sm text-red-700"
                >
                  {issue.nodeId ? <span className="font-semibold">{issue.nodeId}: </span> : null}
                  {issue.message}
                </button>
              ))}
              {validation.warnings.map((issue, index) => (
                <button
                  key={`full-warning-${index}`}
                  type="button"
                  onClick={() => onSelectNode(issue.nodeId ?? null)}
                  className="block w-full rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-left text-sm text-amber-700"
                >
                  {issue.nodeId ? <span className="font-semibold">{issue.nodeId}: </span> : null}
                  {issue.message}
                </button>
              ))}
              {validation.errors.length === 0 && validation.warnings.length === 0 ? (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                  No structural issues detected in the current draft.
                </div>
              ) : null}
              {compilePreviewLoading ? (
                <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-700">
                  Running backend compile preview...
                </div>
              ) : null}
              {compilePreviewError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {compilePreviewError}
                </div>
              ) : null}
              {compilePreview ? (
                <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-3 text-sm text-sky-900">
                  <p className="font-semibold">Backend Compile Preview</p>
                  <div className="mt-2 grid gap-2 text-xs text-sky-800 md:grid-cols-2">
                    <div className="rounded-lg bg-white/70 px-3 py-2">Nodes: {compilePreview.nodes.length}</div>
                    <div className="rounded-lg bg-white/70 px-3 py-2">Edges: {compilePreview.edges.length}</div>
                    <div className="rounded-lg bg-white/70 px-3 py-2">Missing Inputs: {compilePreview.variables.missing_inputs.length}</div>
                    <div className="rounded-lg bg-white/70 px-3 py-2">External Calls: {compilePreview.external_calls.length}</div>
                  </div>
                  {compilePreview.variables.missing_inputs.length > 0 ? (
                    <p className="mt-2 text-xs text-amber-700">
                      Missing inputs: {compilePreview.variables.missing_inputs.join(", ")}
                    </p>
                  ) : null}
                  <p className="mt-2 text-xs text-sky-800">
                    Reachable route: {compilePreview.route_trace.map((entry) => entry.node_id).join(" -> ") || "none"}
                  </p>
                </div>
              ) : null}
            </div>
          </section>
          ) : (
          <section>
            <div className="mb-3 flex items-center justify-between gap-2">
              <p className="text-xs font-bold uppercase tracking-widest text-neutral-400">CKP Preview</p>
            </div>
            <pre className="max-h-full overflow-auto rounded-2xl bg-neutral-950 p-3 text-[11px] text-neutral-100">
              {previewJson}
            </pre>
          </section>
          )}
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3 px-4 py-2 text-xs text-neutral-500">
          <span>Canvas is prioritized. Expand panels when you need validation details or raw CKP preview.</span>
          <span className="rounded-full bg-neutral-100 px-2.5 py-1 text-neutral-600">dock hidden</span>
        </div>
      )}
    </div>
  );
}