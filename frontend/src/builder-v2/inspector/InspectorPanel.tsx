import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import type { BuilderDraftDocument, BuilderNodeDraft, BuilderTransition } from "@/builder-v2/reference-contract";
import type { BuilderNodeRegistryEntry } from "@/builder-v2/registry/node-definitions";
import { RegistryNodeConfigEditor } from "@/builder-v2/inspector/RegistryNodeConfigEditor";

interface InspectorPanelProps {
  draft: BuilderDraftDocument;
  selectedNode: BuilderNodeDraft | null;
  selectedNodeDefinition: BuilderNodeRegistryEntry | null;
  configEditorValue: string;
  configEditorError: string | null;
  onEditorValidationChange?: (errors: string[]) => void;
  onUpdateNode: (patch: Partial<BuilderNodeDraft>) => void;
  onUpdateConfig: (patch: Record<string, unknown>) => void;
  onSetStartNode: () => void;
  onDeleteNode: () => void;
  onAddTransition: (key?: string) => void;
  onUpdateTransition: (transitionKey: string, patch: { key?: string; targetNodeId?: string | null }) => void;
  onRemoveTransition: (transitionKey: string) => void;
  onConfigEditorChange: (value: string) => void;
  onCommitConfigEditor: (value: string) => void;
}

function RetrySettings({ node, onUpdateConfig }: { node: BuilderNodeDraft; onUpdateConfig: (patch: Record<string, unknown>) => void }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div>
        <label htmlFor="builder-v2-failure-node" className="mb-1 block text-xs font-medium text-neutral-500">On Failure Node</label>
        <input
          id="builder-v2-failure-node"
          value={(node.config.on_failure as string | undefined) ?? (node.config.onFailureNode as string | undefined) ?? ""}
          onChange={(event) => onUpdateConfig({ on_failure: event.target.value, onFailureNode: event.target.value })}
          className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
        />
      </div>
      <div>
        <label htmlFor="builder-v2-retry-attempts" className="mb-1 block text-xs font-medium text-neutral-500">Retry Max Attempts</label>
        <input
          id="builder-v2-retry-attempts"
          type="number"
          value={(node.config.retryMaxAttempts as number | undefined) ?? ((node.config.retry as { max_attempts?: number } | undefined)?.max_attempts ?? "")}
          onChange={(event) => onUpdateConfig({
            retryMaxAttempts: event.target.value ? Number(event.target.value) : undefined,
            retry: event.target.value ? {
              max_attempts: Number(event.target.value),
              backoff_ms: (node.config.retryBackoffMs as number | undefined) ?? ((node.config.retry as { backoff_ms?: number } | undefined)?.backoff_ms),
            } : undefined,
          })}
          className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
        />
      </div>
      <div>
        <label htmlFor="builder-v2-retry-backoff" className="mb-1 block text-xs font-medium text-neutral-500">Retry Backoff (ms)</label>
        <input
          id="builder-v2-retry-backoff"
          type="number"
          value={(node.config.retryBackoffMs as number | undefined) ?? ((node.config.retry as { backoff_ms?: number } | undefined)?.backoff_ms ?? "")}
          onChange={(event) => onUpdateConfig({
            retryBackoffMs: event.target.value ? Number(event.target.value) : undefined,
            retry: event.target.value || node.config.retryMaxAttempts ? {
              max_attempts: (node.config.retryMaxAttempts as number | undefined) ?? ((node.config.retry as { max_attempts?: number } | undefined)?.max_attempts),
              backoff_ms: event.target.value ? Number(event.target.value) : undefined,
            } : undefined,
          })}
          className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
        />
      </div>
    </div>
  );
}

function InspectorSection({
  title,
  description,
  defaultOpen = true,
  storageKey,
  children,
}: {
  title: string;
  description?: string;
  defaultOpen?: boolean;
  storageKey?: string;
  children: ReactNode;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  useEffect(() => {
    if (!storageKey || typeof window === "undefined") {
      return;
    }

    const storedValue = window.localStorage.getItem(storageKey);
    if (storedValue === "open") {
      setIsOpen(true);
    } else if (storedValue === "closed") {
      setIsOpen(false);
    }
  }, [storageKey]);

  useEffect(() => {
    if (!storageKey || typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(storageKey, isOpen ? "open" : "closed");
  }, [isOpen, storageKey]);

  return (
    <section className="rounded-2xl border border-neutral-200 bg-white">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        className="sticky top-0 z-10 flex w-full items-start justify-between gap-3 rounded-t-2xl bg-white px-4 py-3 text-left"
      >
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-neutral-400">{title}</p>
          {description ? <p className="mt-1 text-xs leading-5 text-neutral-500">{description}</p> : null}
        </div>
        <span className="rounded-full border border-neutral-200 px-2 py-1 text-[10px] font-medium text-neutral-500">
          {isOpen ? "Collapse" : "Expand"}
        </span>
      </button>
      {isOpen ? <div className="border-t border-neutral-100 px-4 py-3">{children}</div> : null}
    </section>
  );
}

function TransitionEditor({
  draft,
  selectedNode,
  selectedNodeDefinition,
  onAddTransition,
  onUpdateTransition,
  onRemoveTransition,
}: {
  draft: BuilderDraftDocument;
  selectedNode: BuilderNodeDraft;
  selectedNodeDefinition: BuilderNodeRegistryEntry | null;
  onAddTransition: (key?: string) => void;
  onUpdateTransition: (transitionKey: string, patch: { key?: string; targetNodeId?: string | null }) => void;
  onRemoveTransition: (transitionKey: string) => void;
}) {
  const transitionPresetKeys = (selectedNodeDefinition?.transitionKeys ?? []).filter(
    (key) => !selectedNode.transitions.some((transition) => transition.key === key),
  );

  return (
    <div>
      {transitionPresetKeys.length > 0 ? (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {transitionPresetKeys.map((presetKey) => (
            <button
              key={`${selectedNode.id}-preset-${presetKey}`}
              type="button"
              onClick={() => onAddTransition(presetKey)}
              className="rounded-full border border-neutral-200 bg-neutral-50 px-2.5 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-100"
            >
              Add {presetKey}
            </button>
          ))}
        </div>
      ) : null}
      <div className="space-y-1.5">
        {selectedNode.transitions.map((transition: BuilderTransition) => (
          <div key={`${selectedNode.id}-${transition.key}`} className="rounded-xl border border-neutral-200 px-2.5 py-2.5 text-xs text-neutral-600">
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-neutral-400">{transition.key}</p>
                <button
                  type="button"
                  onClick={() => onRemoveTransition(transition.key)}
                  className="rounded-lg border border-neutral-200 px-2 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
                >
                  Remove
                </button>
              </div>
              <div>
                <label htmlFor={`transition-key-${selectedNode.id}-${transition.key}`} className="mb-1 block text-[11px] font-medium text-neutral-500">Edge Label</label>
                <input
                  id={`transition-key-${selectedNode.id}-${transition.key}`}
                  value={transition.key}
                  placeholder="next"
                  aria-label="Transition label"
                  onChange={(event) => onUpdateTransition(transition.key, { key: event.target.value || "next" })}
                  className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
                />
              </div>
              <div>
                <label htmlFor={`transition-target-${selectedNode.id}-${transition.key}`} className="mb-1 block text-[11px] font-medium text-neutral-500">Target Node</label>
                <select
                  id={`transition-target-${selectedNode.id}-${transition.key}`}
                  value={transition.targetNodeId ?? ""}
                  aria-label="Transition target node"
                  onChange={(event) => onUpdateTransition(transition.key, { targetNodeId: event.target.value || null })}
                  className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
                >
                  <option value="">Unset</option>
                  {draft.nodes.filter((node) => node.id !== selectedNode.id).map((node) => (
                    <option key={node.id} value={node.id}>{node.title} ({node.id})</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={() => onAddTransition()}
        className="mt-2 rounded-xl border border-neutral-200 px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
      >
        Add Custom Transition
      </button>
    </div>
  );
}

export function InspectorPanel({
  draft,
  selectedNode,
  selectedNodeDefinition,
  configEditorValue,
  configEditorError,
  onEditorValidationChange,
  onUpdateNode,
  onUpdateConfig,
  onSetStartNode,
  onDeleteNode,
  onAddTransition,
  onUpdateTransition,
  onRemoveTransition,
  onConfigEditorChange,
  onCommitConfigEditor,
}: InspectorPanelProps) {
  useEffect(() => {
    if (!selectedNodeDefinition?.editorLayout) {
      onEditorValidationChange?.([]);
    }
  }, [onEditorValidationChange, selectedNodeDefinition?.editorLayout]);

  if (!selectedNode) {
    return (
      <div className="rounded-2xl border border-dashed border-neutral-300 p-6 text-sm text-neutral-500">
        Select a draft node to inspect and edit it.
      </div>
    );
  }

  const sectionStoragePrefix = `builder-v2:inspector:${selectedNode.kind}:`;

  return (
    <div className="space-y-3">
      <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-neutral-900">{selectedNodeDefinition?.title ?? selectedNode.title}</p>
            <p className="mt-1 text-xs uppercase tracking-wide text-neutral-400">{selectedNode.kind}</p>
          </div>
          <span className="rounded-full bg-white px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-neutral-500">
            {selectedNodeDefinition?.category ?? "node"}
          </span>
        </div>
        {selectedNodeDefinition?.summary ? (
          <p className="mt-2 text-xs leading-5 text-neutral-600">{selectedNodeDefinition.summary}</p>
        ) : null}
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-neutral-500">
          <span className="rounded-full bg-white px-2.5 py-1">id: {selectedNode.id}</span>
          {draft.startNodeId === selectedNode.id ? <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-emerald-700">start node</span> : null}
        </div>
      </div>

      <InspectorSection
        title="Identity"
        description="Name the node clearly so the canvas and transitions stay readable."
        storageKey={`${sectionStoragePrefix}identity`}
      >
        <div className="space-y-4">
          <div>
            <label htmlFor="builder-v2-title" className="mb-1 block text-xs font-medium text-neutral-500">Title</label>
            <input
              id="builder-v2-title"
              value={selectedNode.title}
              onChange={(event) => onUpdateNode({ title: event.target.value })}
              className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
            />
          </div>
          <div>
            <label htmlFor="builder-v2-description" className="mb-1 block text-xs font-medium text-neutral-500">Description</label>
            <textarea
              id="builder-v2-description"
              rows={3}
              value={selectedNode.description ?? ""}
              onChange={(event) => onUpdateNode({ description: event.target.value })}
              className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
            />
          </div>
          <div>
            <label htmlFor="builder-v2-agent" className="mb-1 block text-xs font-medium text-neutral-500">Agent</label>
            <input
              id="builder-v2-agent"
              value={selectedNode.agent ?? ""}
              onChange={(event) => onUpdateNode({ agent: event.target.value || null })}
              className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
            />
          </div>
        </div>
      </InspectorSection>

      {selectedNodeDefinition?.editorLayout ? (
        <InspectorSection
          title="Behavior"
          description="Use the guided form for the node-specific settings exposed by the registry."
          storageKey={`${sectionStoragePrefix}behavior`}
        >
          <RegistryNodeConfigEditor
            node={selectedNode}
            layout={selectedNodeDefinition.editorLayout}
            onUpdateConfig={onUpdateConfig}
            onValidationChange={onEditorValidationChange}
          />
        </InspectorSection>
      ) : null}

      <InspectorSection
        title="Resilience"
        description="Retry and failure routing influence how execution behaves under load or errors."
        defaultOpen={false}
        storageKey={`${sectionStoragePrefix}resilience`}
      >
        <RetrySettings node={selectedNode} onUpdateConfig={onUpdateConfig} />
      </InspectorSection>

      <InspectorSection
        title="Actions"
        description="Promote the node to workflow entry or remove it from the draft."
        defaultOpen={false}
        storageKey={`${sectionStoragePrefix}actions`}
      >
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onSetStartNode}
            className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            Set As Start Node
          </button>
          <button
            type="button"
            onClick={onDeleteNode}
            className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
          >
            Delete Node
          </button>
        </div>
      </InspectorSection>

      <InspectorSection
        title="Transitions"
        description="Define the named exits for this node and connect them to downstream targets."
        defaultOpen={false}
        storageKey={`${sectionStoragePrefix}transitions`}
      >
        <TransitionEditor
          draft={draft}
          selectedNode={selectedNode}
          selectedNodeDefinition={selectedNodeDefinition}
          onAddTransition={onAddTransition}
          onUpdateTransition={onUpdateTransition}
          onRemoveTransition={onRemoveTransition}
        />
      </InspectorSection>

      <InspectorSection
        title="Advanced JSON"
        description="Keep this as the escape hatch for fields that are not yet represented in the guided editor."
        defaultOpen={false}
        storageKey={`${sectionStoragePrefix}advanced-json`}
      >
        <div>
          <label htmlFor="builder-v2-config-json" className="mb-2 block text-xs font-medium text-neutral-500">Advanced Config JSON</label>
          <textarea
            id="builder-v2-config-json"
            rows={6}
            value={configEditorValue}
            onChange={(event) => onConfigEditorChange(event.target.value)}
            onBlur={(event) => onCommitConfigEditor(event.target.value)}
            className="w-full rounded-2xl border border-neutral-200 px-3 py-2 font-mono text-[11px] outline-none focus:border-indigo-400"
          />
          {configEditorError ? (
            <p className="mt-2 text-xs text-red-600">{configEditorError}</p>
          ) : (
            <p className="mt-2 text-xs text-neutral-500">Use this for fields not surfaced yet in the guided inspector.</p>
          )}
        </div>
      </InspectorSection>
    </div>
  );
}
