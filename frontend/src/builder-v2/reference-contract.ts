export type BuilderNodeKind =
  | "sequence"
  | "logic"
  | "loop"
  | "parallel"
  | "human_approval"
  | "llm_action"
  | "processing"
  | "verification"
  | "transform"
  | "subflow"
  | "terminate";

export interface BuilderNodePosition {
  x: number;
  y: number;
}

export interface BuilderTransition {
  key: string;
  targetNodeId: string | null;
  label?: string;
}

export interface BuilderNodeDraft {
  id: string;
  kind: BuilderNodeKind;
  title: string;
  description?: string;
  agent?: string | null;
  position: BuilderNodePosition;
  config: Record<string, unknown>;
  transitions: BuilderTransition[];
  ui?: {
    colorToken?: string;
    collapsed?: boolean;
    notes?: string;
  };
}

export interface BuilderDraftDocument {
  procedureId: string;
  procedureVersion: string;
  startNodeId: string | null;
  nodes: BuilderNodeDraft[];
  viewport?: {
    x: number;
    y: number;
    zoom: number;
  };
  validation?: {
    errors: Array<{ nodeId?: string; message: string }>;
    warnings: Array<{ nodeId?: string; message: string }>;
  };
}

export interface BuilderNodeDefinition {
  kind: BuilderNodeKind;
  title: string;
  category: "deterministic" | "intelligent" | "control";
  transitionKeys: string[];
  defaultConfig: Record<string, unknown>;
}

export interface CkpWorkflowGraph {
  start_node?: string;
  nodes?: Record<string, Record<string, unknown>>;
}

export interface BuilderTransformContract {
  toDraft(workflowGraph: CkpWorkflowGraph): BuilderDraftDocument;
  toCkp(draft: BuilderDraftDocument): CkpWorkflowGraph;
}

export const referenceBuilderModuleLayout = {
  shell: "frontend/src/builder-v2/components/BuilderShell.tsx",
  canvas: "frontend/src/builder-v2/canvas/BuilderCanvas.tsx",
  inspector: "frontend/src/builder-v2/inspector/InspectorPanel.tsx",
  store: "frontend/src/builder-v2/store/builder-store.ts",
  registry: "frontend/src/builder-v2/registry/node-definitions.ts",
  transforms: {
    toDraft: "frontend/src/builder-v2/transforms/ckp-to-draft.ts",
    toCkp: "frontend/src/builder-v2/transforms/draft-to-ckp.ts",
  },
  preview: "frontend/src/builder-v2/preview/CompilePreviewPanel.tsx",
  api: "frontend/src/builder-v2/api/draft-api.ts",
} as const;