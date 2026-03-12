import { useEffect, useMemo, useState } from "react";

import type { BuilderDraftDocument, BuilderNodeDraft } from "@/builder-v2/reference-contract";
import type { BuilderNodeRegistryEntry } from "@/builder-v2/registry/node-definitions";
import type { BuilderRunOverlay } from "@/builder-v2/execution/run-overlay";

import { TYPE_ICONS, WORKFLOW_TEMPLATES } from "@/builder-v2/legacy/catalog";

type BuilderIssue = { nodeId?: string; message: string };

interface BuilderLeftRailProps {
  draft: BuilderDraftDocument;
  selectedNodeId: string | null;
  paletteFilter: string;
  outlineFilter: string;
  filteredNodeDefinitions: BuilderNodeRegistryEntry[];
  filteredDraftNodes: BuilderNodeDraft[];
  issuesByNodeId: Map<string, { errors: number; warnings: number }>;
  validation: { errors: BuilderIssue[]; warnings: BuilderIssue[] };
  runOverlay: BuilderRunOverlay | null;
  runSummary: {
    label: string;
    className: string;
    detail: string;
    isActive: boolean;
  } | null;
  runStateTotals: {
    idle: number;
    current: number;
    running: number;
    completed: number;
    failed: number;
    paused: number;
    sla_breached: number;
  } | null;
  traversedEdgeCount: number;
  onPaletteFilterChange: (value: string) => void;
  onOutlineFilterChange: (value: string) => void;
  onAddNode: (kind: BuilderNodeRegistryEntry["kind"]) => void;
  onSelectNode: (nodeId: string | null) => void;
  onApplyTemplate: (templateName: string) => void;
}

export function BuilderLeftRail({
  draft,
  selectedNodeId,
  paletteFilter,
  outlineFilter,
  filteredNodeDefinitions,
  filteredDraftNodes,
  issuesByNodeId,
  validation,
  runOverlay,
  runSummary,
  runStateTotals,
  traversedEdgeCount,
  onPaletteFilterChange,
  onOutlineFilterChange,
  onAddNode,
  onSelectNode,
  onApplyTemplate,
}: BuilderLeftRailProps) {
  const [activeView, setActiveView] = useState<"library" | "outline" | "templates" | "health">("library");
  const [openCategories, setOpenCategories] = useState<Record<string, boolean>>({});
  const [summaryOpen, setSummaryOpen] = useState(false);
  const paletteByCategory = useMemo(() => {
    const grouped = new Map<string, BuilderNodeRegistryEntry[]>();
    for (const definition of filteredNodeDefinitions) {
      const category = definition.category || "other";
      const entries = grouped.get(category) ?? [];
      entries.push(definition);
      grouped.set(category, entries);
    }
    return Array.from(grouped.entries()).map(([category, definitions]) => ({
      category,
      definitions,
    }));
  }, [filteredNodeDefinitions]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    try {
      const storedSummary = window.localStorage.getItem("builder-v2:left-rail:summary");
      const storedCategories = window.localStorage.getItem("builder-v2:left-rail:categories");
      if (storedSummary === "open") {
        setSummaryOpen(true);
      }
      if (storedCategories) {
        setOpenCategories(JSON.parse(storedCategories) as Record<string, boolean>);
      }
    } catch {
      // Ignore malformed persisted rail state.
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem("builder-v2:left-rail:summary", summaryOpen ? "open" : "closed");
  }, [summaryOpen]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem("builder-v2:left-rail:categories", JSON.stringify(openCategories));
  }, [openCategories]);

  function isCategoryOpen(category: string, index: number) {
    return openCategories[category] ?? index < 2;
  }

  return (
    <aside className="flex h-full min-h-0 flex-col bg-white p-4">
      <div className="mb-3 rounded-2xl border border-neutral-200 bg-neutral-50">
        <button
          type="button"
          onClick={() => setSummaryOpen((current) => !current)}
          className="flex w-full items-start justify-between gap-3 px-2.5 py-2.5 text-left"
        >
          <div>
            <p className="text-sm font-semibold text-neutral-800">Builder V2</p>
            <p className="mt-0.5 text-[11px] leading-4 text-neutral-600">Canvas-first editing with focused side tools.</p>
          </div>
          <div className="flex flex-col items-end gap-1">
            <span className="rounded-full bg-white px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-neutral-500">
              {draft.nodes.length} nodes
            </span>
            <span className="rounded-full border border-neutral-200 bg-white px-2 py-0.5 text-[10px] font-medium text-neutral-500">
              {summaryOpen ? "Collapse" : "Expand"}
            </span>
          </div>
        </button>
        {summaryOpen ? (
          <div className="border-t border-neutral-200 px-2.5 py-2.5">
            <div className="flex flex-wrap gap-2 text-[11px]">
              <span className={`rounded-full px-2 py-1 ${validation.errors.length > 0 ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"}`}>
                {validation.errors.length} errors
              </span>
              <span className="rounded-full bg-amber-100 px-2 py-1 text-amber-700">{validation.warnings.length} warnings</span>
              {runSummary ? <span className={`rounded-full px-2 py-1 ${runSummary.className}`}>{runSummary.label}</span> : null}
            </div>
          </div>
        ) : null}
      </div>

      <div className="mb-3 grid grid-cols-2 gap-1 rounded-2xl border border-neutral-200 bg-neutral-50 p-1 text-xs font-medium">
        {[
          { key: "library", label: "Library" },
          { key: "outline", label: "Outline" },
          { key: "templates", label: "Templates" },
          { key: "health", label: "Health" },
        ].map((view) => (
          <button
            key={view.key}
            type="button"
            onClick={() => setActiveView(view.key as "library" | "outline" | "templates" | "health")}
            className={activeView === view.key
              ? "rounded-xl bg-white px-2.5 py-1.5 text-neutral-900 shadow-sm"
              : "rounded-xl px-2.5 py-1.5 text-neutral-500 hover:bg-white/70"}
          >
            {view.label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {activeView === "library" ? (
          <div>
            <div className="mb-4">
              <label htmlFor="builder-v2-palette-filter" className="mb-1.5 block text-xs font-bold uppercase tracking-widest text-neutral-400">Find Nodes</label>
              <input
                id="builder-v2-palette-filter"
                value={paletteFilter}
                onChange={(event) => onPaletteFilterChange(event.target.value)}
                placeholder="Search palette"
                className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
              />
            </div>

            <p className="mb-2 text-xs font-bold uppercase tracking-widest text-neutral-400">Palette</p>
            <div className="space-y-2">
              {paletteByCategory.map(({ category, definitions }, index) => {
                const open = isCategoryOpen(category, index);
                return (
                  <section key={category} className="rounded-xl border border-neutral-200 bg-neutral-50/60">
                    <button
                      type="button"
                      onClick={() => setOpenCategories((current) => ({ ...current, [category]: !open }))}
                      className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left"
                    >
                      <span>
                        <span className="text-[10px] font-bold uppercase tracking-widest text-neutral-400">{category}</span>
                        <span className="ml-2 text-[11px] text-neutral-500">{definitions.length}</span>
                      </span>
                      <span className="rounded-full border border-neutral-200 bg-white px-2 py-0.5 text-[10px] font-medium text-neutral-500">
                        {open ? "Collapse" : "Expand"}
                      </span>
                    </button>
                    {open ? (
                      <div className="space-y-1 border-t border-neutral-200 bg-white px-2 py-2">
                        {definitions.map((definition) => (
                          <button
                            key={definition.kind}
                            draggable
                            onDragStart={(event) => {
                              event.dataTransfer.setData("application/builder-node-kind", definition.kind);
                              event.dataTransfer.effectAllowed = "copy";
                            }}
                            onClick={() => onAddNode(definition.kind)}
                            className="flex w-full items-start gap-2 rounded-xl border border-neutral-200 px-2 py-1.5 text-left hover:border-neutral-300 hover:bg-neutral-50 cursor-grab active:cursor-grabbing"
                          >
                            <span className="pt-0.5 text-sm text-neutral-700">{TYPE_ICONS[definition.kind] ?? "●"}</span>
                            <span className="min-w-0 flex-1">
                              <span className="block text-[13px] font-medium text-neutral-700">{definition.title}</span>
                              <span className="mt-0.5 line-clamp-2 block text-[11px] leading-4 text-neutral-500">{definition.summary}</span>
                            </span>
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </section>
                );
              })}
              {filteredNodeDefinitions.length === 0 ? (
                <div className="rounded-xl border border-dashed border-neutral-200 px-3 py-3 text-xs text-neutral-500">
                  No node types match the current search.
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {activeView === "outline" ? (
          <div>
            <div className="mb-3 flex items-center justify-between gap-2">
              <p className="text-xs font-bold uppercase tracking-widest text-neutral-400">Draft Outline</p>
              <span className="text-[10px] uppercase tracking-widest text-neutral-400">{draft.nodes.length} nodes</span>
            </div>
            <input
              value={outlineFilter}
              onChange={(event) => onOutlineFilterChange(event.target.value)}
              placeholder="Search nodes"
              className="mb-3 w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
            />
            <div className="space-y-2">
              {filteredDraftNodes.map((node) => {
                const issueCounts = issuesByNodeId.get(node.id);
                const isSelected = node.id === selectedNodeId;
                const nodeRunState = runOverlay?.nodeStates[node.id]?.state ?? "idle";
                const nodeLoopCount = runOverlay?.nodeStates[node.id]?.loopCount;
                return (
                  <button
                    key={node.id}
                    onClick={() => onSelectNode(node.id)}
                    className={`block w-full rounded-xl border px-3 py-2 text-left ${isSelected ? "border-indigo-300 bg-indigo-50" : "border-neutral-200 hover:border-neutral-300 hover:bg-neutral-50"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2 text-sm font-medium text-neutral-800">
                        <span>{TYPE_ICONS[node.kind] ?? "●"}</span>
                        <span className="truncate">{node.title}</span>
                      </span>
                      {draft.startNodeId === node.id ? <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">start</span> : null}
                      {nodeRunState === "current" ? <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-700">live</span> : null}
                      {nodeRunState === "running" ? <span className="rounded-full bg-cyan-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-cyan-700">running</span> : null}
                      {nodeRunState === "completed" ? <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">done</span> : null}
                      {nodeRunState === "paused" ? <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700">waiting</span> : null}
                      {nodeRunState === "failed" ? <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-rose-700">failed</span> : null}
                      {nodeRunState === "sla_breached" ? <span className="rounded-full bg-fuchsia-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-fuchsia-700">sla</span> : null}
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-[11px] text-neutral-500">
                      <span>{node.id}</span>
                      <span className="uppercase tracking-wide">{node.kind}</span>
                      {nodeLoopCount ? <span className="rounded-full bg-violet-100 px-2 py-0.5 text-violet-700">loop {nodeLoopCount}</span> : null}
                      {issueCounts?.errors ? <span className="rounded-full bg-red-100 px-2 py-0.5 text-red-700">{issueCounts.errors} err</span> : null}
                      {issueCounts?.warnings ? <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-700">{issueCounts.warnings} warn</span> : null}
                    </div>
                  </button>
                );
              })}
              {filteredDraftNodes.length === 0 ? (
                <div className="rounded-xl border border-dashed border-neutral-200 px-3 py-3 text-xs text-neutral-500">
                  No draft nodes match the current search.
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {activeView === "templates" ? (
          <div>
            <p className="mb-2 text-xs font-bold uppercase tracking-widest text-neutral-400">Starter Templates</p>
            <p className="mb-3 text-xs text-neutral-500">Load a reference flow, then adapt the canvas instead of assembling every draft from scratch.</p>
            <div className="space-y-2">
              {WORKFLOW_TEMPLATES.map((template) => (
                <button
                  key={template.name}
                  onClick={() => onApplyTemplate(template.name)}
                  className="block w-full rounded-xl border border-neutral-200 px-3 py-2 text-left hover:border-neutral-300 hover:bg-neutral-50"
                >
                  <div className="flex items-center gap-2 text-sm font-medium text-neutral-700">
                    <span>{template.icon}</span>
                    <span>{template.name}</span>
                  </div>
                  <p className="mt-1 text-xs text-neutral-500">{template.description}</p>
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {activeView === "health" ? (
          <div className="space-y-4">
            {runSummary ? (
              <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-600">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-semibold text-neutral-800">Run Overlay</p>
                  <span className={`rounded-full px-2 py-1 ${runSummary.className}`}>{runSummary.label}</span>
                </div>
                <p className="mt-2 leading-5">{runSummary.detail}</p>
                {runSummary.isActive ? <p className="mt-2 text-[11px] text-neutral-500">The latest run is still active on the canvas.</p> : null}
                {runStateTotals ? (
                  <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                    {runStateTotals.completed > 0 ? <span className="rounded-full bg-emerald-100 px-2 py-1 text-emerald-700">{runStateTotals.completed} done</span> : null}
                    {runStateTotals.paused > 0 ? <span className="rounded-full bg-amber-100 px-2 py-1 text-amber-700">{runStateTotals.paused} waiting</span> : null}
                    {runStateTotals.failed > 0 ? <span className="rounded-full bg-rose-100 px-2 py-1 text-rose-700">{runStateTotals.failed} failed</span> : null}
                    {runStateTotals.sla_breached > 0 ? <span className="rounded-full bg-fuchsia-100 px-2 py-1 text-fuchsia-700">{runStateTotals.sla_breached} sla</span> : null}
                    {traversedEdgeCount > 0 ? <span className="rounded-full bg-teal-100 px-2 py-1 text-teal-700">{traversedEdgeCount} traversed edges</span> : null}
                  </div>
                ) : null}
              </div>
            ) : null}

            <div>
              <p className="mb-3 text-xs font-bold uppercase tracking-widest text-neutral-400">Validation Snapshot</p>
              <div className="space-y-2">
                {validation.errors.length === 0 && validation.warnings.length === 0 ? (
                  <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
                    Draft looks structurally healthy.
                  </div>
                ) : null}
                {validation.errors.slice(0, 4).map((issue, index) => (
                  <div key={`error-${index}`} className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                    {issue.nodeId ? `${issue.nodeId}: ` : ""}{issue.message}
                  </div>
                ))}
                {validation.warnings.slice(0, 4).map((issue, index) => (
                  <div key={`warning-${index}`} className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                    {issue.nodeId ? `${issue.nodeId}: ` : ""}{issue.message}
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </aside>
  );
}
