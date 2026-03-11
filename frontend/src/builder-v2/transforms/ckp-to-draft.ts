import type { BuilderDraftDocument, BuilderTransition, CkpWorkflowGraph } from "@/builder-v2/reference-contract";
import { ckpToRf } from "@/builder-v2/legacy/transforms";

export function ckpWorkflowToDraftDocument(
  workflowGraph: CkpWorkflowGraph,
  options?: { procedureId?: string; procedureVersion?: string },
): BuilderDraftDocument {
  const { nodes, edges } = ckpToRf((workflowGraph ?? {}) as Record<string, unknown>);

  return {
    procedureId: options?.procedureId ?? "reference-procedure",
    procedureVersion: options?.procedureVersion ?? "draft",
    startNodeId: (workflowGraph.start_node as string | undefined) ?? null,
    nodes: nodes.map((node) => {
      const transitions: BuilderTransition[] = edges
        .filter((edge) => edge.source === node.id)
        .map((edge) => ({
          key: typeof edge.label === "string" && edge.label.length > 0 ? edge.label : "next",
          label: typeof edge.label === "string" && edge.label.length > 0 ? edge.label : undefined,
          targetNodeId: edge.target,
        }));

      return {
        id: node.id,
        kind: node.data.nodeType,
        title: node.data.label,
        description: node.data.description || undefined,
        agent: node.data.agent || null,
        position: node.position,
        config: {
          ...node.data.extra,
          status: node.data.status,
          approvalPrompt: node.data.approvalPrompt,
          decisionType: node.data.decisionType,
          timeoutMs: node.data.timeoutMs,
          llmPrompt: node.data.llmPrompt,
          llmModel: node.data.llmModel,
          orchestrationMode: node.data.orchestrationMode,
          orchestrationBranches: node.data.orchestrationBranches,
          loopMaxIterations: node.data.loopMaxIterations,
          loopContinueCondition: node.data.loopContinueCondition,
          parallelWaitAll: node.data.parallelWaitAll,
          logicDefaultNext: node.data.logicDefaultNext,
          action: node.data.action,
          inputMapping: node.data.inputMapping,
          outputMapping: node.data.outputMapping,
          transformer: node.data.transformer,
          verificationRules: node.data.verificationRules,
          subflowId: node.data.subflowId,
          subflowVersion: node.data.subflowVersion,
          onFailureNode: node.data.onFailureNode,
          retryMaxAttempts: node.data.retryMaxAttempts,
          retryBackoffMs: node.data.retryBackoffMs,
          extraJsonText: node.data.extraJsonText,
          steps: node.data.steps,
          checks: node.data.checks,
          outputs: node.data.outputs,
          isCheckpoint: node.data.isCheckpoint,
        },
        transitions,
      };
    }),
  };
}