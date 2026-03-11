import type { Edge, Node } from "@xyflow/react";

import { rfToCkp } from "@/builder-v2/legacy/transforms";
import type { BuilderDraftDocument, CkpWorkflowGraph } from "@/builder-v2/reference-contract";
import type { BuilderNodeData } from "@/builder-v2/legacy/types";

export function draftDocumentToCkpWorkflow(draft: BuilderDraftDocument): CkpWorkflowGraph {
  const nodes: Node<BuilderNodeData>[] = draft.nodes.map((node) => ({
    id: node.id,
    type: "builderNode",
    position: node.position,
    data: {
      label: node.title,
      nodeType: node.kind,
      description: node.description ?? "",
      agent: node.agent ?? "",
      isStart: draft.startNodeId === node.id,
      isCheckpoint: !!node.config.isCheckpoint,
      status: typeof node.config.status === "string" ? node.config.status : undefined,
      approvalPrompt: typeof node.config.approvalPrompt === "string" ? node.config.approvalPrompt : undefined,
      decisionType: typeof node.config.decisionType === "string" ? node.config.decisionType : undefined,
      timeoutMs: typeof node.config.timeoutMs === "number" ? node.config.timeoutMs : undefined,
      llmPrompt: typeof node.config.llmPrompt === "string" ? node.config.llmPrompt : undefined,
      llmModel: typeof node.config.llmModel === "string" ? node.config.llmModel : undefined,
      orchestrationMode: !!node.config.orchestrationMode,
      orchestrationBranches: typeof node.config.orchestrationBranches === "string" ? node.config.orchestrationBranches : undefined,
      loopMaxIterations: typeof node.config.loopMaxIterations === "number" ? node.config.loopMaxIterations : undefined,
      loopContinueCondition: typeof node.config.loopContinueCondition === "string" ? node.config.loopContinueCondition : undefined,
      parallelWaitAll: typeof node.config.parallelWaitAll === "boolean" ? node.config.parallelWaitAll : undefined,
      logicDefaultNext: typeof node.config.logicDefaultNext === "string" ? node.config.logicDefaultNext : undefined,
      action: typeof node.config.action === "string" ? node.config.action : undefined,
      inputMapping: typeof node.config.inputMapping === "string" ? node.config.inputMapping : undefined,
      outputMapping: typeof node.config.outputMapping === "string" ? node.config.outputMapping : undefined,
      transformer: typeof node.config.transformer === "string" ? node.config.transformer : undefined,
      verificationRules: typeof node.config.verificationRules === "string" ? node.config.verificationRules : undefined,
      subflowId: typeof node.config.subflowId === "string" ? node.config.subflowId : undefined,
      subflowVersion: typeof node.config.subflowVersion === "string" ? node.config.subflowVersion : undefined,
      onFailureNode: typeof node.config.onFailureNode === "string" ? node.config.onFailureNode : undefined,
      retryMaxAttempts: typeof node.config.retryMaxAttempts === "number" ? node.config.retryMaxAttempts : undefined,
      retryBackoffMs: typeof node.config.retryBackoffMs === "number" ? node.config.retryBackoffMs : undefined,
      extraJsonText: typeof node.config.extraJsonText === "string" ? node.config.extraJsonText : undefined,
      steps: Array.isArray(node.config.steps) ? (node.config.steps as Record<string, unknown>[]) : undefined,
      checks: Array.isArray(node.config.checks) ? (node.config.checks as Record<string, unknown>[]) : undefined,
      outputs: node.config.outputs && typeof node.config.outputs === "object" ? (node.config.outputs as Record<string, unknown>) : undefined,
      extra: node.config,
    },
  }));

  const edges: Edge[] = draft.nodes.flatMap((node) =>
    node.transitions
      .filter((transition) => transition.targetNodeId)
      .map((transition, index) => ({
        id: `${node.id}-${transition.key}-${transition.targetNodeId ?? index}`,
        source: node.id,
        target: transition.targetNodeId as string,
        label: transition.key === "next" ? undefined : transition.key,
      })),
  );

  return rfToCkp(nodes, edges);
}