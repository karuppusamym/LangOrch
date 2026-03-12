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
  { key: "step_id", label: "Step ID", description: "Stable identifier used when this step is referenced in runtime logs or results.", required: true, keyEditable: false, valuePlaceholder: "fetch_customer_profile" },
  {
    key: "action",
    label: "Action",
    description: "What this step actually does inside the sequence.",
    required: true,
    keyEditable: false,
    valueInput: "select",
    valueOptions: ["fetch", "transform", "notify", "call_api", "log"],
    valuePresets: {
      fetch: { binding_kind: "connector", binding_ref: "data_source" },
      transform: { binding_kind: "function", binding_ref: "normalize_payload" },
      notify: { binding_kind: "channel", binding_ref: "email" },
      call_api: { binding_kind: "connector", binding_ref: "http.default" },
      log: { binding_kind: "none" },
    },
  },
  { key: "binding_kind", label: "Binding Kind", description: "Select where the step resolves its implementation from.", required: true, keyEditable: false, valueInput: "select", valueOptions: ["connector", "function", "channel", "agent", "none"], visibleWhen: (value) => String(value.action ?? "").trim().length > 0 },
  { key: "binding_ref", label: "Binding Ref", description: "Registry key or named reference used by the selected binding kind.", required: true, keyEditable: false, valuePlaceholder: "crm.lookup_customer", visibleWhen: (value) => {
    const bindingKind = String(value.binding_kind ?? "").trim();
    return bindingKind.length > 0 && bindingKind !== "none";
  } },
];

const logicRuleFields: EditorFieldDefinition[] = [
  { key: "expression", label: "Expression", description: "Boolean condition evaluated to decide whether this rule matches.", required: true, keyEditable: false, valueInput: "textarea", valueRows: 3, valuePlaceholder: "priority == 'high'" },
  { key: "next", label: "Next Node", description: "Node ID to route to when the expression evaluates to true.", required: true, keyEditable: false, valuePlaceholder: "expedite_path" },
];

const verificationRuleFields: EditorFieldDefinition[] = [
  { key: "expression", label: "Check", description: "Validation expression to run against the current workflow context.", required: true, keyEditable: false, valueInput: "textarea", valueRows: 3, valuePlaceholder: "customer_email != ''" },
  { key: "severity", label: "Severity", description: "How strongly a failed check should affect execution or operator attention.", required: true, keyEditable: false, valueInput: "select", valueOptions: ["error", "warning", "info"] },
];

const branchFields: EditorFieldDefinition[] = [
  { key: "name", label: "Branch Name", description: "Label used to identify the branch in the runtime fan-out and results.", required: true, keyEditable: false, valuePlaceholder: "research" },
  { key: "target", label: "Target Node", description: "Node ID this parallel branch should execute.", required: true, keyEditable: false, valuePlaceholder: "research_node" },
];

const mappingFields: EditorFieldDefinition[] = [
  { key: "customer_input", label: "Customer Input", keyEditable: false, valuePlaceholder: "{{vars.customer_input}}" },
  { key: "case_id", label: "Case ID", keyEditable: false, valuePlaceholder: "{{vars.case_id}}" },
  { key: "previous_result", label: "Previous Result", keyEditable: false, valuePlaceholder: "{{vars.result}}" },
];

const outputFields: EditorFieldDefinition[] = [
  { key: "result", label: "Result", description: "Primary payload returned by this terminal node.", keyEditable: false, valuePlaceholder: "{{vars.result}}" },
  { key: "status", label: "Status", description: "Final run status emitted when execution terminates here.", keyEditable: false, valuePlaceholder: "success" },
  { key: "decision", label: "Decision", description: "Decision value surfaced to callers or downstream consumers.", keyEditable: false, valuePlaceholder: "{{vars.decision}}" },
];

const processingOperationTemplates: EditorTemplate[] = [
  { label: "Set Variable", value: { action: "set_variable", variable: "result", value: "{{vars.input}}" } },
  { label: "Log", value: { action: "log", message: "Processing {{run_id}}", level: "INFO" } },
  { label: "Screenshot", value: { action: "screenshot", name: "capture", output_variable: "screenshot_result" } },
];

const processingOperationFields: EditorFieldDefinition[] = [
  {
    key: "action",
    label: "Action",
    description: "Operation the processing node should perform for this item.",
    required: true,
    keyEditable: false,
    valueInput: "select",
    valueOptions: ["set_variable", "log", "screenshot", "notify", "http_request"],
    valuePresets: {
      set_variable: { variable: "result", value: "{{vars.input}}", output_variable: "result" },
      log: { message: "Processing started", level: "INFO" },
      screenshot: { name: "capture", output_variable: "screenshot_result" },
      notify: { message: "Run update" },
      http_request: { output_variable: "http_result" },
    },
  },
  { key: "variable", label: "Variable", description: "Workflow variable name that will receive the computed value.", required: true, keyEditable: false, valuePlaceholder: "result", visibleWhen: (value) => String(value.action ?? "") === "set_variable" },
  { key: "value", label: "Value", description: "Literal or templated value assigned into the target variable.", required: true, keyEditable: false, valueInput: "textarea", valueRows: 3, valuePlaceholder: "{{vars.input}}", visibleWhen: (value) => String(value.action ?? "") === "set_variable" },
  { key: "message", label: "Message", description: "Text payload emitted to logs or notification channels.", required: true, keyEditable: false, valueInput: "textarea", valueRows: 3, valuePlaceholder: "Processing started", visibleWhen: (value) => {
    const action = String(value.action ?? "");
    return action === "log" || action === "notify";
  } },
  { key: "level", label: "Level", description: "Severity used when the action writes a log event.", required: true, keyEditable: false, valueInput: "select", valueOptions: ["DEBUG", "INFO", "WARNING", "ERROR"], visibleWhen: (value) => String(value.action ?? "") === "log" },
  { key: "name", label: "Name", description: "Human-readable artifact name for captured screenshots or attachments.", required: true, keyEditable: false, valuePlaceholder: "capture", visibleWhen: (value) => String(value.action ?? "") === "screenshot" },
  { key: "output_variable", label: "Output Variable", description: "Variable that stores the result produced by this operation.", required: true, keyEditable: false, valuePlaceholder: "result", visibleWhen: (value) => {
    const action = String(value.action ?? "");
    return action === "screenshot" || action === "http_request" || action === "set_variable";
  } },
];

const transformOperationTemplates: EditorTemplate[] = [
  { label: "Filter", value: { type: "filter", source_variable: "items", expression: "{{item.active}} == true", output_variable: "filtered_items" } },
  { label: "Map", value: { type: "map", source_variable: "items", expression: "{{item.name}}", output_variable: "item_names" } },
  { label: "Aggregate", value: { type: "aggregate", source_variable: "items", expression: "count", output_variable: "item_count", params: { op: "count" } } },
];

const transformOperationFields: EditorFieldDefinition[] = [
  {
    key: "type",
    label: "Type",
    description: "Transformation strategy applied to the source collection or value.",
    required: true,
    keyEditable: false,
    valueInput: "select",
    valueOptions: ["filter", "map", "aggregate"],
    valuePresets: {
      filter: { source_variable: "items", expression: "{{item.active}} == true", output_variable: "filtered_items" },
      map: { source_variable: "items", expression: "{{item.name}}", output_variable: "item_names" },
      aggregate: { source_variable: "items", expression: "count", output_variable: "item_count", params: { op: "count" } },
    },
  },
  { key: "source_variable", label: "Source Variable", description: "Variable to read before applying the transformation.", required: true, keyEditable: false, valuePlaceholder: "items" },
  { key: "expression", label: "Expression", description: "Mapping, filter, or aggregate expression evaluated for each source item.", required: true, keyEditable: false, valueInput: "textarea", valueRows: 3, valuePlaceholder: "{{item.name}}" },
  { key: "output_variable", label: "Output Variable", description: "Variable that receives the transformed result.", required: true, keyEditable: false, valuePlaceholder: "result" },
  { key: "params", label: "Params", description: "Additional aggregate configuration expressed as JSON.", keyEditable: false, valueInput: "textarea", valueRows: 3, valuePlaceholder: '{"op":"count"}', visibleWhen: (value) => String(value.type ?? "") === "aggregate" },
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
        { kind: "text", label: "Iterator Variable", keys: ["iterator"], validation: { required: true } },
        { kind: "text", label: "Current Item Variable", keys: ["iterator_variable"], validation: { required: true } },
        { kind: "text", label: "Index Variable", keys: ["index_variable"] },
        { kind: "text", label: "Collect Variable", keys: ["collect_variable"] },
        { kind: "number", label: "Max Iterations", keys: ["max_iterations", "loopMaxIterations"] },
        { kind: "checkbox", label: "Continue On Error", keys: ["continue_on_error"], defaultValue: false },
      ],
    },
  ],
  parallel: [
    {
      title: "Execution",
      controls: [
        { kind: "checkbox", label: "Wait for all branches", keys: ["parallelWaitAll", "wait_all"], defaultValue: true },
        { kind: "select", label: "Branch Failure", keys: ["branch_failure"], defaultValue: "continue", options: ["continue", "fail"] },
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
      title: "Operations",
      controls: [
        {
          kind: "object-list",
          label: "Operations",
          keys: ["operations"],
          newItem: { action: "", output_variable: "" },
          addItemLabel: "Add Operation",
          fields: processingOperationFields,
          templates: processingOperationTemplates,
          validation: { minItems: 1, message: "Processing nodes need at least one operation." },
        },
      ],
    },
  ],
  transform: [
    {
      title: "Transformations",
      controls: [
        {
          kind: "object-list",
          label: "Transformations",
          keys: ["transformations"],
          newItem: { type: "", source_variable: "", expression: "", output_variable: "" },
          addItemLabel: "Add Transformation",
          fields: transformOperationFields,
          templates: transformOperationTemplates,
          validation: { minItems: 1, message: "Transform nodes need at least one transformation." },
        },
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