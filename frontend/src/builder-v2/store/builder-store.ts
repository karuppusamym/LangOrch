import type { BuilderDraftDocument, BuilderNodeDraft, BuilderNodeKind } from "@/builder-v2/reference-contract";
import { builderNodeBlueprints } from "@/builder-v2/registry/node-definitions";
import { dagreLayout } from "@/builder-v2/legacy/transforms";

const nodeDefinitionMap = Object.fromEntries(
  builderNodeBlueprints.map((definition) => [definition.kind, definition]),
) as Record<BuilderNodeKind, (typeof builderNodeBlueprints)[number]>;

function normalizeLegacyProcessingConfig(config: Record<string, unknown>): Record<string, unknown> {
  const operations = config.operations;
  if (Array.isArray(operations) && operations.length > 0) {
    return { ...config };
  }

  const action = typeof config.action === "string" ? config.action.trim() : "";
  if (!action) {
    return { ...config };
  }

  const legacyInputMapping = config.input_mapping;
  const legacyInputMappingText = config.inputMapping;
  const legacyOutputMapping = config.output_mapping;
  const legacyOutputMappingText = config.outputMapping;

  let normalizedOperation: Record<string, unknown> = { action };

  const mergeMapping = (value: unknown) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      normalizedOperation = { ...normalizedOperation, ...(value as Record<string, unknown>) };
      return;
    }
    if (typeof value === "string" && value.trim()) {
      try {
        const parsed = JSON.parse(value);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          normalizedOperation = { ...normalizedOperation, ...(parsed as Record<string, unknown>) };
        }
      } catch {
        // Keep non-JSON strings untouched; they were never reliably executable.
      }
    }
  };

  mergeMapping(legacyInputMapping);
  mergeMapping(legacyInputMappingText);
  mergeMapping(legacyOutputMapping);
  mergeMapping(legacyOutputMappingText);

  const {
    action: _legacyAction,
    input_mapping: _legacyInputMapping,
    inputMapping: _legacyInputMappingText,
    output_mapping: _legacyOutputMapping,
    outputMapping: _legacyOutputMappingText,
    ...rest
  } = config;

  return {
    ...rest,
    operations: [normalizedOperation],
  };
}

function normalizeLoadedNode(node: BuilderNodeDraft): BuilderNodeDraft {
  const normalizedConfig = node.kind === "processing"
    ? normalizeLegacyProcessingConfig(node.config)
    : { ...node.config };

  return {
    ...node,
    transitions: [...node.transitions],
    config: normalizedConfig,
    ui: node.ui ? { ...node.ui } : undefined,
  };
}

export function createEmptyDraftDocument(overrides?: Partial<BuilderDraftDocument>): BuilderDraftDocument {
  return {
    procedureId: overrides?.procedureId ?? "reference-procedure",
    procedureVersion: overrides?.procedureVersion ?? "draft",
    startNodeId: overrides?.startNodeId ?? null,
    nodes: overrides?.nodes ?? [],
    viewport: overrides?.viewport,
    validation: overrides?.validation,
  };
}

export function addDraftNode(draft: BuilderDraftDocument, kind: BuilderNodeKind): BuilderDraftDocument {
  const definition = nodeDefinitionMap[kind];
  let nextIndex = draft.nodes.length + 1;
  let nodeId = `${kind}_${nextIndex}`;
  while (draft.nodes.some((node) => node.id === nodeId)) {
    nextIndex += 1;
    nodeId = `${kind}_${nextIndex}`;
  }
  const node: BuilderNodeDraft = {
    id: nodeId,
    kind,
    title: definition.title,
    description: "",
    agent: null,
    position: { x: 96, y: 96 + draft.nodes.length * 104 },
    config: { ...definition.defaultConfig },
    transitions: definition.transitionKeys.map((key) => ({ key, targetNodeId: null })),
  };

  return {
    ...draft,
    startNodeId: draft.startNodeId ?? nodeId,
    nodes: [...draft.nodes, node],
  };
}

export function updateDraftNode(
  draft: BuilderDraftDocument,
  nodeId: string,
  patch: Partial<BuilderNodeDraft>,
): BuilderDraftDocument {
  return {
    ...draft,
    nodes: draft.nodes.map((node) => (node.id === nodeId ? { ...node, ...patch } : node)),
  };
}

export function updateDraftNodeConfig(
  draft: BuilderDraftDocument,
  nodeId: string,
  patch: Record<string, unknown>,
): BuilderDraftDocument {
  return {
    ...draft,
    nodes: draft.nodes.map((node) => (
      node.id === nodeId
        ? { ...node, config: { ...node.config, ...patch } }
        : node
    )),
  };
}

export function updateDraftTransition(
  draft: BuilderDraftDocument,
  nodeId: string,
  transitionKey: string,
  patch: { key?: string; targetNodeId?: string | null },
): BuilderDraftDocument {
  return {
    ...draft,
    nodes: draft.nodes.map((node) => (
      node.id === nodeId
        ? {
            ...node,
            transitions: node.transitions.map((transition) => (
              transition.key === transitionKey ? { ...transition, ...patch } : transition
            )),
          }
        : node
    )),
  };
}

export function addDraftTransition(
  draft: BuilderDraftDocument,
  nodeId: string,
  key = "next",
): BuilderDraftDocument {
  return {
    ...draft,
    nodes: draft.nodes.map((node) => (
      node.id === nodeId
        ? { ...node, transitions: [...node.transitions, { key, targetNodeId: null }] }
        : node
    )),
  };
}

export function removeDraftTransition(
  draft: BuilderDraftDocument,
  nodeId: string,
  transitionKey: string,
): BuilderDraftDocument {
  return {
    ...draft,
    nodes: draft.nodes.map((node) => (
      node.id === nodeId
        ? { ...node, transitions: node.transitions.filter((transition) => transition.key !== transitionKey) }
        : node
    )),
  };
}

export function removeDraftNode(draft: BuilderDraftDocument, nodeId: string): BuilderDraftDocument {
  const remainingNodes = draft.nodes
    .filter((node) => node.id !== nodeId)
    .map((node) => ({
      ...node,
      transitions: node.transitions.map((transition) => (
        transition.targetNodeId === nodeId ? { ...transition, targetNodeId: null } : transition
      )),
    }));

  return {
    ...draft,
    startNodeId: draft.startNodeId === nodeId ? remainingNodes[0]?.id ?? null : draft.startNodeId,
    nodes: remainingNodes,
  };
}

export function updateDraftNodePositions(
  draft: BuilderDraftDocument,
  positions: Array<{ id: string; position: { x: number; y: number } }>,
): BuilderDraftDocument {
  const positionMap = new Map(positions.map((item) => [item.id, item.position]));
  return {
    ...draft,
    nodes: draft.nodes.map((node) => ({
      ...node,
      position: positionMap.get(node.id) ?? node.position,
    })),
  };
}

export function autoLayoutDraft(draft: BuilderDraftDocument): BuilderDraftDocument {
  const positions = dagreLayout(
    draft.nodes.map((node) => ({ id: node.id })),
    draft.nodes.flatMap((node) => node.transitions
      .filter((transition) => transition.targetNodeId)
      .map((transition) => ({ source: node.id, target: transition.targetNodeId as string }))),
  );

  return {
    ...draft,
    nodes: draft.nodes.map((node) => ({
      ...node,
      position: positions.get(node.id) ?? node.position,
    })),
  };
}

export function duplicateDraftNode(
  draft: BuilderDraftDocument,
  sourceNodeId: string,
  offset = { x: 48, y: 48 },
): BuilderDraftDocument {
  const source = draft.nodes.find((node) => node.id === sourceNodeId);
  if (!source) return draft;

  let nextIndex = draft.nodes.length + 1;
  let newId = `${source.kind}_${nextIndex}`;
  while (draft.nodes.some((node) => node.id === newId)) {
    nextIndex += 1;
    newId = `${source.kind}_${nextIndex}`;
  }

  const duplicate: BuilderNodeDraft = {
    ...source,
    id: newId,
    title: `${source.title} (copy)`,
    position: { x: source.position.x + offset.x, y: source.position.y + offset.y },
    transitions: source.transitions.map((t) => ({ ...t, targetNodeId: null })),
  };

  return { ...draft, nodes: [...draft.nodes, duplicate] };
}

export function setDraftStartNode(draft: BuilderDraftDocument, nodeId: string): BuilderDraftDocument {
  return {
    ...draft,
    startNodeId: nodeId,
  };
}

export function loadDraftDocument(draft: BuilderDraftDocument): BuilderDraftDocument {
  return {
    ...draft,
    nodes: draft.nodes.map((node) => normalizeLoadedNode(node)),
  };
}