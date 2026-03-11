import type { BuilderDraftDocument } from "@/builder-v2/reference-contract";

export function validateDraftDocument(draft: BuilderDraftDocument) {
  const errors: Array<{ nodeId?: string; message: string }> = [];
  const warnings: Array<{ nodeId?: string; message: string }> = [];

  if (draft.nodes.length === 0) {
    warnings.push({ message: "This draft has no nodes yet." });
    return { errors, warnings };
  }

  const nodeMap = new Map(draft.nodes.map((node) => [node.id, node]));

  if (!draft.startNodeId) {
    errors.push({ message: "A start node is required before this workflow can be published." });
  } else if (!nodeMap.has(draft.startNodeId)) {
    errors.push({ message: `The selected start node '${draft.startNodeId}' does not exist in this draft.` });
  }

  for (const node of draft.nodes) {
    if (!node.title.trim()) {
      warnings.push({ nodeId: node.id, message: "This step has no title yet." });
    }

    if (node.kind !== "terminate" && node.transitions.length === 0) {
      warnings.push({ nodeId: node.id, message: "This step has no outgoing path yet." });
    }

    for (const transition of node.transitions) {
      if (!transition.targetNodeId) {
        warnings.push({ nodeId: node.id, message: `Transition '${transition.key}' does not point to a target yet.` });
        continue;
      }

      if (!nodeMap.has(transition.targetNodeId)) {
        errors.push({ nodeId: node.id, message: `Transition '${transition.key}' points to missing node '${transition.targetNodeId}'.` });
      }
    }

    if (node.kind === "human_approval") {
      const keys = new Set(node.transitions.map((transition) => transition.key));
      if (!keys.has("approve")) {
        warnings.push({ nodeId: node.id, message: "Approval step is missing an approve path." });
      }
      if (!keys.has("reject")) {
        warnings.push({ nodeId: node.id, message: "Approval step is missing a reject path." });
      }
    }
  }

  if (draft.startNodeId && nodeMap.has(draft.startNodeId)) {
    const visited = new Set<string>();
    const queue = [draft.startNodeId];
    while (queue.length > 0) {
      const current = queue.shift() as string;
      if (visited.has(current)) continue;
      visited.add(current);
      const node = nodeMap.get(current);
      if (!node) continue;
      for (const transition of node.transitions) {
        if (transition.targetNodeId && !visited.has(transition.targetNodeId)) {
          queue.push(transition.targetNodeId);
        }
      }
    }

    for (const node of draft.nodes) {
      if (!visited.has(node.id)) {
        warnings.push({ nodeId: node.id, message: "This step is not reachable from the current start node." });
      }
    }
  }

  return { errors, warnings };
}