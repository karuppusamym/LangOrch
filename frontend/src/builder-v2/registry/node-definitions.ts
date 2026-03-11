import type { BuilderNodeDefinition, BuilderNodeKind } from "@/builder-v2/reference-contract";
import type { BuilderNodeEditorSection } from "@/builder-v2/inspector/editor-schema";
import { builderNodeEditorLayouts } from "@/builder-v2/registry/node-editor-layouts";

export interface BuilderNodeBlueprint extends BuilderNodeDefinition {
	summary: string;
}

export interface BuilderNodeRegistryEntry extends BuilderNodeBlueprint {
	editorLayout?: BuilderNodeEditorSection[];
}

export const builderNodeBlueprints: BuilderNodeBlueprint[] = [
	{
		kind: "sequence",
		title: "Sequence",
		category: "deterministic",
		summary: "Run a deterministic list of steps with explicit bindings and ordered execution.",
		transitionKeys: ["next"],
		defaultConfig: { steps: [] },
	},
	{
		kind: "logic",
		title: "Logic",
		category: "control",
		summary: "Route the workflow using rule expressions, default paths, and outcome branches.",
		transitionKeys: ["true", "false", "default"],
		defaultConfig: { rules: [] },
	},
	{
		kind: "loop",
		title: "Loop",
		category: "control",
		summary: "Repeat work until a continue condition fails or the iteration cap is reached.",
		transitionKeys: ["loop body", "done"],
		defaultConfig: { max_iterations: 10, continue_condition: "" },
	},
	{
		kind: "parallel",
		title: "Parallel",
		category: "control",
		summary: "Fan out into named branches and optionally wait for all branches to finish.",
		transitionKeys: ["branch"],
		defaultConfig: { wait_all: true, branches: [] },
	},
	{
		kind: "human_approval",
		title: "Approval",
		category: "control",
		summary: "Pause the run for a human decision with approval, rejection, and timeout outcomes.",
		transitionKeys: ["approve", "reject", "timeout"],
		defaultConfig: { prompt: "", decision_type: "approve_reject" },
	},
	{
		kind: "llm_action",
		title: "LLM Action",
		category: "intelligent",
		summary: "Invoke a model prompt and optionally enable orchestration behavior for branching flows.",
		transitionKeys: ["next"],
		defaultConfig: { prompt: "", model: "" },
	},
	{
		kind: "processing",
		title: "Processing",
		category: "deterministic",
		summary: "Execute a deterministic action with explicit input and output mappings.",
		transitionKeys: ["pass", "fail", "error"],
		defaultConfig: { action: "", input_mapping: {}, output_mapping: {} },
	},
	{
		kind: "verification",
		title: "Verification",
		category: "control",
		summary: "Evaluate checks and branch on verification pass or fail outcomes.",
		transitionKeys: ["pass", "fail"],
		defaultConfig: { rules: [] },
	},
	{
		kind: "transform",
		title: "Transform",
		category: "deterministic",
		summary: "Reshape payloads with a named transformer and explicit mapping contracts.",
		transitionKeys: ["next"],
		defaultConfig: { transformer: "", input_mapping: {}, output_mapping: {} },
	},
	{
		kind: "subflow",
		title: "Subflow",
		category: "deterministic",
		summary: "Delegate execution to another procedure version and continue when it returns.",
		transitionKeys: ["next"],
		defaultConfig: { subflow_id: "", version: "" },
	},
	{
		kind: "terminate",
		title: "Terminate",
		category: "control",
		summary: "Finish the workflow with a final status and shaped output payload.",
		transitionKeys: [],
		defaultConfig: { status: "success", outputs: {} },
	},
];

export const builderNodeDefinitions: BuilderNodeRegistryEntry[] = builderNodeBlueprints.map((definition) => ({
	...definition,
	editorLayout: builderNodeEditorLayouts[definition.kind],
}));

const builderNodeDefinitionMap = Object.fromEntries(
	builderNodeDefinitions.map((definition) => [definition.kind, definition]),
) as Record<BuilderNodeKind, BuilderNodeRegistryEntry>;

export function getBuilderNodeDefinition(kind: BuilderNodeKind): BuilderNodeRegistryEntry {
	return builderNodeDefinitionMap[kind];
}