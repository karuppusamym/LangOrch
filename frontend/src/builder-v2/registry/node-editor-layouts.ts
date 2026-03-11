import type { BuilderNodeKind } from "@/builder-v2/reference-contract";
import type { BuilderNodeEditorSection } from "@/builder-v2/inspector/editor-schema";
import type { EditorFieldDefinition, EditorTemplate } from "@/builder-v2/inspector/shared/structured-editors";

const sequenceStepTemplates: EditorTemplate[] = [
  { label: "Fetch Data", value: { step_id: "fetch_data", action: "fetch", binding_kind: "connector", binding_ref: "data_source" } },
  { label: "Transform", value: { step_id: "transform_data", action: "transform", binding_kind: "function", binding_ref: "normalize_payload" } },
  { label: "Notify", value: { step_id: "notify_user", action: "notify", binding_kind: "channel", binding_ref: "email" } },
];

const logicRuleTemplates: EditorTemplate[] = [
  { label: "Approved Path", value: { expression: "approval_status == 'approved'", next: "approved_path" } },
  { label: "High Priority", value: { expression: "priority == 'high'", next: "expedite_path" } },
];

const verificationRuleTemplates: EditorTemplate[] = [
  { label: "Required Field", value: { expression: "customer_email != ''", severity: "error" } },
  { label: "Confidence Check", value: { expression: "confidence >= 0.8", severity: "warning" } },
];

const parallelBranchTemplates: EditorTemplate[] = [
  { label: "Research Branch", value: { name: "research", target: "research_node" } },
  { label: "Fulfillment Branch", value: { name: "fulfillment", target: "fulfillment_node" } },
];

const mappingTemplates: EditorTemplate[] = [
  { label: "Customer Input", value: { customer_input: "{{vars.customer_input}}" } },
  { label: "Case Context", value: { case_id: "{{vars.case_id}}", project_id: "{{vars.project_id}}" } },
  { label: "Previous Result", value: { previous_result: "{{vars.result}}" } },
];

const outputTemplates: EditorTemplate[] = [
  { label: "Result Payload", value: { result: "{{vars.result}}" } },
  { label: "Decision Status", value: { status: "success", decision: "{{vars.decision}}" } },
];

const stepFields: EditorFieldDefinition[] = [
  { key: "step_id", label: "Step ID", keyEditable: false, valuePlaceholder: "fetch_customer_profile" },
  { key: "action", label: "Action", keyEditable: false, valuePlaceholder: "fetch" },
  { key: "binding_kind", label: "Binding Kind", keyEditable: false, valuePlaceholder: "connector | function | channel" },
  { key: "binding_ref", label: "Binding Ref", keyEditable: false, valuePlaceholder: "crm.lookup_customer" },
];

const logicRuleFields: EditorFieldDefinition[] = [
  { key: "expression", label: "Expression", keyEditable: false, valuePlaceholder: "priority == 'high'" },
  { key: "next", label: "Next Node", keyEditable: false, valuePlaceholder: "expedite_path" },
];

const verificationRuleFields: EditorFieldDefinition[] = [
  { key: "expression", label: "Check", keyEditable: false, valuePlaceholder: "customer_email != ''" },
  { key: "severity", label: "Severity", keyEditable: false, valuePlaceholder: "error | warning" },
];

const branchFields: EditorFieldDefinition[] = [
  { key: "name", label: "Branch Name", keyEditable: false, valuePlaceholder: "research" },
  { key: "target", label: "Target Node", keyEditable: false, valuePlaceholder: "research_node" },
];

const mappingFields: EditorFieldDefinition[] = [
  { key: "customer_input", label: "Customer Input", keyEditable: false, valuePlaceholder: "{{vars.customer_input}}" },
  { key: "case_id", label: "Case ID", keyEditable: false, valuePlaceholder: "{{vars.case_id}}" },
  { key: "previous_result", label: "Previous Result", keyEditable: false, valuePlaceholder: "{{vars.result}}" },
];

const outputFields: EditorFieldDefinition[] = [
  { key: "result", label: "Result", keyEditable: false, valuePlaceholder: "{{vars.result}}" },
  { key: "status", label: "Status", keyEditable: false, valuePlaceholder: "success" },
  { key: "decision", label: "Decision", keyEditable: false, valuePlaceholder: "{{vars.decision}}" },
];

export const builderNodeEditorLayouts: Partial<Record<BuilderNodeKind, BuilderNodeEditorSection[]>> = {
  human_approval: [
    {
      title: "Approval",
      controls: [
        { kind: "textarea", label: "Approval Prompt", keys: ["prompt"], rows: 3, validation: { required: true } },
        { kind: "text", label: "Decision Type", keys: ["decision_type"], defaultValue: "approve_reject" },
        { kind: "number", label: "Timeout (ms)", keys: ["timeoutMs", "timeout_ms"] },
      ],
    },
  ],
  llm_action: [
    {
      title: "Prompt",
      controls: [
        { kind: "text", label: "Model", keys: ["llmModel", "model"], validation: { required: true } },
        { kind: "textarea", label: "Prompt", keys: ["llmPrompt", "prompt"], rows: 4, validation: { required: true } },
      ],
    },
    {
      title: "Orchestration",
      controls: [
        { kind: "checkbox", label: "Enable orchestration mode", keys: ["orchestrationMode", "orchestration_mode"] },
        { kind: "text", label: "Orchestration Branches", keys: ["orchestrationBranches"], placeholder: "branch_a, branch_b" },
      ],
    },
  ],
  sequence: [
    {
      title: "Steps",
      controls: [
        {
          kind: "object-list",
          label: "Steps",
          keys: ["steps"],
          newItem: { step_id: "", action: "" },
          addItemLabel: "Add Step",
          fields: stepFields,
          templates: sequenceStepTemplates,
          validation: { minItems: 1, message: "Steps must include at least one item." },
        },
      ],
    },
  ],
  logic: [
    {
      title: "Rules",
      controls: [
        {
          kind: "object-list",
          label: "Rules",
          keys: ["rules"],
          newItem: { expression: "", next: "" },
          addItemLabel: "Add Rule",
          fields: logicRuleFields,
          templates: logicRuleTemplates,
          validation: { minItems: 1, message: "Rules must include at least one item." },
        },
      ],
    },
    {
      title: "Fallback",
      controls: [
        { kind: "text", label: "Default Next Node", keys: ["logicDefaultNext", "default_next"] },
      ],
    },
  ],
  terminate: [
    {
      title: "Outcome",
      controls: [
        { kind: "select", label: "Terminal Status", keys: ["status"], defaultValue: "success", options: ["success", "failed", "cancelled"] },
      ],
    },
    {
      title: "Outputs",
      controls: [
        { kind: "object", label: "Outputs", keys: ["outputs"], fields: outputFields, templates: outputTemplates },
      ],
    },
  ],
  loop: [
    {
      title: "Loop Control",
      controls: [
        { kind: "number", label: "Max Iterations", keys: ["max_iterations", "loopMaxIterations"] },
        { kind: "textarea", label: "Continue Condition", keys: ["continue_condition", "loopContinueCondition"], rows: 3 },
      ],
    },
  ],
  parallel: [
    {
      title: "Execution",
      controls: [
        { kind: "checkbox", label: "Wait for all branches", keys: ["parallelWaitAll", "wait_all"], defaultValue: true },
      ],
    },
    {
      title: "Branches",
      controls: [
        {
          kind: "object-list",
          label: "Branches",
          keys: ["branches"],
          newItem: { name: "", target: "" },
          addItemLabel: "Add Branch",
          fields: branchFields,
          templates: parallelBranchTemplates,
          validation: { minItems: 1, message: "Branches must include at least one branch." },
        },
      ],
    },
  ],
  processing: [
    {
      title: "Processing",
      controls: [
        { kind: "text", label: "Action", keys: ["action"], validation: { required: true } },
      ],
    },
    {
      title: "Input Mapping",
      controls: [
        { kind: "object", label: "Input Mapping", keys: ["input_mapping", "inputMapping"], fields: mappingFields, templates: mappingTemplates },
      ],
    },
    {
      title: "Output Mapping",
      controls: [
        { kind: "object", label: "Output Mapping", keys: ["output_mapping", "outputMapping"], fields: outputFields, templates: outputTemplates },
      ],
    },
  ],
  transform: [
    {
      title: "Transform",
      controls: [
        { kind: "text", label: "Transformer", keys: ["transformer"], validation: { required: true } },
      ],
    },
    {
      title: "Input Mapping",
      controls: [
        { kind: "object", label: "Input Mapping", keys: ["input_mapping", "inputMapping"], fields: mappingFields, templates: mappingTemplates },
      ],
    },
    {
      title: "Output Mapping",
      controls: [
        { kind: "object", label: "Output Mapping", keys: ["output_mapping", "outputMapping"], fields: outputFields, templates: outputTemplates },
      ],
    },
  ],
  verification: [
    {
      title: "Rules",
      controls: [
        {
          kind: "object-list",
          label: "Rules",
          keys: ["rules", "checks"],
          newItem: { expression: "", severity: "" },
          addItemLabel: "Add Rule",
          fields: verificationRuleFields,
          templates: verificationRuleTemplates,
          validation: { minItems: 1, message: "Rules must include at least one item." },
        },
      ],
    },
  ],
  subflow: [
    {
      title: "Reference",
      controls: [
        { kind: "text", label: "Subflow ID", keys: ["subflow_id", "subflowId"], validation: { required: true } },
        { kind: "text", label: "Subflow Version", keys: ["version", "subflowVersion"] },
      ],
    },
  ],
};