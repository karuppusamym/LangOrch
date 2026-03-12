import type { BuilderDraftDocument, CkpWorkflowGraph } from "@/builder-v2/reference-contract";

type CkpNode = Record<string, unknown>;

const UI_ONLY_CONFIG_KEYS = new Set([
  "approvalPrompt",
  "decisionType",
  "timeoutMs",
  "llmPrompt",
  "llmModel",
  "orchestrationMode",
  "orchestrationBranches",
  "loopMaxIterations",
  "loopContinueCondition",
  "parallelWaitAll",
  "logicDefaultNext",
  "inputMapping",
  "outputMapping",
  "verificationRules",
  "subflowId",
  "subflowVersion",
  "onFailureNode",
  "retryMaxAttempts",
  "retryBackoffMs",
  "extraJsonText",
  "isCheckpoint",
]);

function parseJsonLike(value: unknown): unknown {
  if (typeof value !== "string") {
    return value;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }

  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

function asObject(value: unknown): Record<string, unknown> | undefined {
  const parsed = parseJsonLike(value);
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    return parsed as Record<string, unknown>;
  }
  return undefined;
}

function asArray(value: unknown): Record<string, unknown>[] {
  const parsed = parseJsonLike(value);
  return Array.isArray(parsed)
    ? parsed.filter((item): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item))
    : [];
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function getTransitionTarget(node: BuilderDraftDocument["nodes"][number], ...keys: string[]): string | undefined {
  for (const key of keys) {
    const transition = node.transitions.find((candidate) => candidate.key === key && candidate.targetNodeId);
    if (transition?.targetNodeId) {
      return transition.targetNodeId;
    }
  }
  return undefined;
}

function getConditionalTransitionTargets(node: BuilderDraftDocument["nodes"][number]): string[] {
  return node.transitions
    .filter((transition) => transition.targetNodeId && !["default", "done", "loop body", "next", "approve", "reject", "timeout"].includes(transition.key))
    .map((transition) => transition.targetNodeId as string);
}

function buildBaseNode(node: BuilderDraftDocument["nodes"][number]): CkpNode {
  const base: CkpNode = {
    type: node.kind,
  };

  if (node.description?.trim()) {
    base.description = node.description.trim();
  }
  if (node.agent?.trim()) {
    base.agent = node.agent.trim();
  }
  if (node.config.isCheckpoint) {
    base.is_checkpoint = true;
  }

  for (const [key, value] of Object.entries(node.config)) {
    if (value === undefined || UI_ONLY_CONFIG_KEYS.has(key)) {
      continue;
    }
    base[key] = parseJsonLike(value);
  }

  if (typeof node.config.extraJsonText === "string" && node.config.extraJsonText.trim()) {
    const extra = parseJsonLike(node.config.extraJsonText);
    if (extra && typeof extra === "object" && !Array.isArray(extra)) {
      Object.assign(base, extra);
    }
  }

  return base;
}

function normalizeLogicRules(node: BuilderDraftDocument["nodes"][number]): Record<string, unknown>[] {
  const rawRules = asArray(node.config.rules);
  const transitionTargets = getConditionalTransitionTargets(node);
  const normalized: Record<string, unknown>[] = [];

  rawRules.forEach((rule, index) => {
    const condition = asString(rule.condition) ?? asString(rule.expression);
    const nextNode = asString(rule.next_node) ?? asString(rule.next) ?? transitionTargets[index];
    if (!condition || !nextNode) {
      return;
    }
    normalized.push({ condition, next_node: nextNode });
  });

  return normalized;
}

function normalizeVerificationChecks(node: BuilderDraftDocument["nodes"][number]): Record<string, unknown>[] {
  const rawChecks = asArray(node.config.checks).length > 0 ? asArray(node.config.checks) : asArray(node.config.rules);
  const normalized: Record<string, unknown>[] = [];

  rawChecks.forEach((check, index) => {
    const condition = asString(check.condition) ?? asString(check.expression);
    if (!condition) {
      return;
    }

    const severity = asString(check.severity)?.toLowerCase();
    const onFail = asString(check.on_fail) ?? (severity === "warning" ? "warn" : "fail_workflow");

    normalized.push({
      id: asString(check.id) ?? `check_${index + 1}`,
      condition,
      on_fail: onFail,
      message: asString(check.message) ?? "",
    });
  });

  return normalized;
}

function normalizeParallelBranches(node: BuilderDraftDocument["nodes"][number]): Record<string, unknown>[] {
  const explicitBranches: Record<string, unknown>[] = [];

  asArray(node.config.branches).forEach((branch, index) => {
    const branchId = asString(branch.branch_id) ?? asString(branch.name) ?? `branch_${index + 1}`;
    const startNode = asString(branch.start_node) ?? asString(branch.target) ?? asString(branch.entry_node);
    if (!startNode) {
      return;
    }
    explicitBranches.push({ branch_id: branchId, start_node: startNode });
  });

  if (explicitBranches.length > 0) {
    return explicitBranches;
  }

  return node.transitions
    .filter((transition) => transition.targetNodeId && (transition.key === "branch" || transition.key.startsWith("branch:")))
    .map((transition, index) => ({
      branch_id: transition.key === "branch" ? `branch_${index + 1}` : transition.key.slice(7),
      start_node: transition.targetNodeId as string,
    }));
}

function normalizeProcessingOperations(node: BuilderDraftDocument["nodes"][number]): Record<string, unknown>[] {
  const explicitOperations = asArray(node.config.operations);
  if (explicitOperations.length > 0) {
    return explicitOperations;
  }

  const action = asString(node.config.action);
  if (!action) {
    return [];
  }

  return [{
    action,
    ...(asObject(node.config.input_mapping) ?? asObject(node.config.inputMapping) ?? {}),
    ...(asObject(node.config.output_mapping) ?? asObject(node.config.outputMapping) ?? {}),
  }];
}

export function draftDocumentToCkpWorkflow(draft: BuilderDraftDocument): CkpWorkflowGraph {
  const nodes: Record<string, CkpNode> = {};

  for (const node of draft.nodes) {
    const ckpNode = buildBaseNode(node);

    switch (node.kind) {
      case "logic": {
        const rules = normalizeLogicRules(node);
        if (rules.length > 0) {
          ckpNode.rules = rules;
        }

        const defaultNext =
          asString(node.config.default_next_node) ??
          asString(node.config.default_next) ??
          asString(node.config.logicDefaultNext) ??
          getTransitionTarget(node, "default");
        if (defaultNext) {
          ckpNode.default_next_node = defaultNext;
        }
        break;
      }

      case "loop": {
        const bodyNode = asString(node.config.body_node) ?? getTransitionTarget(node, "loop body");
        const nextNode = asString(node.config.next_node) ?? getTransitionTarget(node, "done", "next");
        const iterator = asString(node.config.iterator);
        const iteratorVariable = asString(node.config.iterator_variable);
        const indexVariable = asString(node.config.index_variable);
        const collectVariable = asString(node.config.collect_variable);
        const maxIterations = asNumber(node.config.max_iterations) ?? asNumber(node.config.loopMaxIterations);
        const continueOnError = asBoolean(node.config.continue_on_error);

        if (iterator) ckpNode.iterator = iterator;
        if (iteratorVariable) ckpNode.iterator_variable = iteratorVariable;
        if (indexVariable) ckpNode.index_variable = indexVariable;
        if (collectVariable) ckpNode.collect_variable = collectVariable;
        if (bodyNode) ckpNode.body_node = bodyNode;
        if (nextNode) ckpNode.next_node = nextNode;
        if (maxIterations !== undefined) ckpNode.max_iterations = maxIterations;
        if (continueOnError !== undefined) ckpNode.continue_on_error = continueOnError;
        break;
      }

      case "parallel": {
        const branches = normalizeParallelBranches(node);
        const nextNode = asString(node.config.next_node) ?? getTransitionTarget(node, "next");
        const waitStrategy = asString(node.config.wait_strategy)
          ?? (asBoolean(node.config.parallelWaitAll) ?? asBoolean(node.config.wait_all)) === false
            ? "any"
            : "all";
        const branchFailure = asString(node.config.branch_failure);

        if (branches.length > 0) {
          ckpNode.branches = branches;
        }
        ckpNode.wait_strategy = waitStrategy;
        if (branchFailure) ckpNode.branch_failure = branchFailure;
        if (nextNode) ckpNode.next_node = nextNode;
        break;
      }

      case "human_approval": {
        const prompt = asString(node.config.prompt) ?? asString(node.config.approvalPrompt);
        const decisionType = asString(node.config.decision_type) ?? asString(node.config.decisionType);
        const timeoutMs = asNumber(node.config.timeout_ms) ?? asNumber(node.config.timeoutMs);
        if (prompt) ckpNode.prompt = prompt;
        if (decisionType) ckpNode.decision_type = decisionType;
        if (timeoutMs !== undefined) ckpNode.timeout_ms = timeoutMs;
        const approveTarget = getTransitionTarget(node, "approve");
        const rejectTarget = getTransitionTarget(node, "reject");
        const timeoutTarget = getTransitionTarget(node, "timeout");
        if (approveTarget) ckpNode.on_approve = approveTarget;
        if (rejectTarget) ckpNode.on_reject = rejectTarget;
        if (timeoutTarget) ckpNode.on_timeout = timeoutTarget;
        break;
      }

      case "llm_action": {
        const prompt = asString(node.config.prompt) ?? asString(node.config.llmPrompt);
        const model = asString(node.config.model) ?? asString(node.config.llmModel);
        const nextNode = asString(node.config.next_node) ?? getTransitionTarget(node, "next");
        const orchestrationMode = asBoolean(node.config.orchestration_mode) ?? asBoolean(node.config.orchestrationMode);
        if (prompt) ckpNode.prompt = prompt;
        if (model) ckpNode.model = model;
        if (nextNode) ckpNode.next_node = nextNode;
        if (orchestrationMode) {
          ckpNode.orchestration_mode = true;
          const rawBranches = asString(node.config.orchestrationBranches);
          if (rawBranches) {
            ckpNode.branches = rawBranches.split(",").map((branch) => branch.trim()).filter(Boolean);
          }
        }
        break;
      }

      case "processing": {
        const operations = normalizeProcessingOperations(node);
        const nextNode = asString(node.config.next_node) ?? getTransitionTarget(node, "next", "pass");
        if (operations.length > 0) {
          ckpNode.operations = operations;
        }
        if (nextNode) {
          ckpNode.next_node = nextNode;
        }
        break;
      }

      case "verification": {
        const checks = normalizeVerificationChecks(node);
        const nextNode = asString(node.config.next_node) ?? getTransitionTarget(node, "next", "pass");
        if (checks.length > 0) {
          ckpNode.checks = checks;
        }
        if (nextNode) {
          ckpNode.next_node = nextNode;
        }
        break;
      }

      case "transform": {
        const transformations = asArray(node.config.transformations);
        const nextNode = asString(node.config.next_node) ?? getTransitionTarget(node, "next");
        if (transformations.length > 0) {
          ckpNode.transformations = transformations;
        }
        if (nextNode) {
          ckpNode.next_node = nextNode;
        }
        break;
      }

      case "subflow": {
        const procedureId = asString(node.config.procedure_id) ?? asString(node.config.subflow_id) ?? asString(node.config.subflowId);
        const version = asString(node.config.version) ?? asString(node.config.subflowVersion);
        const nextNode = asString(node.config.next_node) ?? getTransitionTarget(node, "next");
        if (procedureId) ckpNode.procedure_id = procedureId;
        if (version) ckpNode.version = version;
        if (nextNode) ckpNode.next_node = nextNode;
        const inputMapping = asObject(node.config.input_mapping) ?? asObject(node.config.inputMapping);
        const outputMapping = asObject(node.config.output_mapping) ?? asObject(node.config.outputMapping);
        if (inputMapping) ckpNode.input_mapping = inputMapping;
        if (outputMapping) ckpNode.output_mapping = outputMapping;
        break;
      }

      case "terminate": {
        const status = asString(node.config.status);
        if (status) ckpNode.status = status;
        const outputs = asObject(node.config.outputs);
        if (outputs) ckpNode.outputs = outputs;
        break;
      }

      default: {
        const nextNode = asString(node.config.next_node) ?? getTransitionTarget(node, "next");
        if (nextNode) {
          ckpNode.next_node = nextNode;
        }
        break;
      }
    }

    if (node.kind === "sequence" && Array.isArray(node.config.steps) && node.config.steps.length > 0) {
      ckpNode.steps = node.config.steps as Record<string, unknown>[];
    }

    if (node.kind !== "terminate" && !ckpNode.next_node && node.kind !== "logic" && node.kind !== "human_approval" && node.kind !== "loop" && node.kind !== "parallel") {
      const fallbackNext = getTransitionTarget(node, "next");
      if (fallbackNext) {
        ckpNode.next_node = fallbackNext;
      }
    }

    nodes[node.id] = ckpNode;
  }

  return {
    start_node: draft.startNodeId ?? undefined,
    nodes,
  };
}