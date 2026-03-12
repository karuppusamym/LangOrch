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
      const prompt = (node.config.prompt ?? node.config.approvalPrompt ?? "") as string;
      if (!String(prompt).trim()) {
        warnings.push({ nodeId: node.id, message: "Approval step has no prompt text — reviewers will see a blank request." });
      }
    }

    if (node.kind === "llm_action") {
      const model = (node.config.model ?? node.config.llmModel ?? "") as string;
      const prompt = (node.config.prompt ?? node.config.llmPrompt ?? "") as string;
      if (!String(model).trim()) {
        errors.push({ nodeId: node.id, message: "LLM Action requires a model to be set before it can run." });
      }
      if (!String(prompt).trim()) {
        warnings.push({ nodeId: node.id, message: "LLM Action has no prompt — the model will receive an empty input." });
      }
    }

    if (node.kind === "loop") {
      const iterator = (node.config.iterator ?? "") as string;
      const iteratorVariable = (node.config.iterator_variable ?? "") as string;
      const bodyNode = node.transitions.find((transition) => transition.key === "loop body")?.targetNodeId ?? node.config.body_node;
      if (!String(iterator).trim()) {
        errors.push({ nodeId: node.id, message: "Loop requires an iterator variable name (for example 'items')." });
      }
      if (!String(iteratorVariable).trim()) {
        errors.push({ nodeId: node.id, message: "Loop requires a current item variable to expose each iteration value." });
      }
      if (!String(bodyNode ?? "").trim()) {
        errors.push({ nodeId: node.id, message: "Loop requires a 'loop body' transition target." });
      }
      const maxIter = node.config.max_iterations ?? node.config.loopMaxIterations;
      if (maxIter !== undefined && Number(maxIter) < 1) {
        errors.push({ nodeId: node.id, message: "Loop max iterations must be at least 1." });
      }
    }

    if (node.kind === "subflow") {
      const subflowId = (node.config.subflow_id ?? node.config.subflowId ?? "") as string;
      if (!String(subflowId).trim()) {
        errors.push({ nodeId: node.id, message: "Subflow step requires a procedure ID to delegate to." });
      }
    }

    if (node.kind === "processing") {
      const action = (node.config.action ?? "") as string;
      const operations = node.config.operations;
      if ((!Array.isArray(operations) || operations.length === 0) && !String(action).trim()) {
        errors.push({ nodeId: node.id, message: "Processing step requires an action name." });
      }
      if ((!Array.isArray(operations) || operations.length === 0) && String(action).trim()) {
        warnings.push({ nodeId: node.id, message: "This node still uses the legacy single-action processing shape. Converting it to explicit operations is recommended." });
      }
      if (node.transitions.some((transition) => ["pass", "fail", "error"].includes(transition.key))) {
        warnings.push({ nodeId: node.id, message: "Processing nodes execute a single next path. Legacy pass/fail/error edges are ignored at runtime." });
      }
    }

    if (node.kind === "transform") {
      const transformations = node.config.transformations;
      const transformer = (node.config.transformer ?? "") as string;
      if ((!Array.isArray(transformations) || transformations.length === 0) && !String(transformer).trim()) {
        errors.push({ nodeId: node.id, message: "Transform step requires at least one transformation." });
      }
      if ((!Array.isArray(transformations) || transformations.length === 0) && String(transformer).trim()) {
        warnings.push({ nodeId: node.id, message: "Legacy transformer/input-output mapping config is no longer executable on its own. Add explicit transformations." });
      }
    }

    if (node.kind === "parallel") {
      const branches = node.config.branches;
      if (!Array.isArray(branches) || (branches as unknown[]).length === 0) {
        errors.push({ nodeId: node.id, message: "Parallel node needs at least one branch defined." });
      }
      if (!node.transitions.some((transition) => transition.key === "next" && transition.targetNodeId) && !node.config.next_node) {
        warnings.push({ nodeId: node.id, message: "Parallel node has no join path yet. Add a 'next' transition for the post-merge step." });
      }
    }

    if (node.kind === "sequence") {
      const steps = node.config.steps;
      if (!Array.isArray(steps) || (steps as unknown[]).length === 0) {
        warnings.push({ nodeId: node.id, message: "Sequence node has no steps configured yet." });
      }
    }

    if (node.kind === "verification") {
      if (node.transitions.some((transition) => transition.key === "fail")) {
        warnings.push({ nodeId: node.id, message: "Verification failures are handled inside each check. Separate fail edges are not executed by the backend." });
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

    // Cycle detection via DFS — warn when a back-edge is found that bypasses a loop node
    const cycleVisited = new Set<string>();
    const cycleStack = new Set<string>();
    function detectCycle(nodeId: string): boolean {
      if (cycleStack.has(nodeId)) return true;
      if (cycleVisited.has(nodeId)) return false;
      cycleVisited.add(nodeId);
      cycleStack.add(nodeId);
      const node = nodeMap.get(nodeId);
      if (node) {
        for (const transition of node.transitions) {
          if (transition.targetNodeId && detectCycle(transition.targetNodeId)) {
            if (!errors.some((e) => e.nodeId === nodeId && e.message.includes("cycle"))) {
              errors.push({ nodeId, message: `Cycle detected: '${nodeId}' eventually loops back to itself. Use a Loop node to model intentional repetition.` });
            }
            cycleStack.delete(nodeId);
            return true;
          }
        }
      }
      cycleStack.delete(nodeId);
      return false;
    }
    for (const node of draft.nodes) {
      if (!cycleVisited.has(node.id)) {
        detectCycle(node.id);
      }
    }
  }

  return { errors, warnings };
}