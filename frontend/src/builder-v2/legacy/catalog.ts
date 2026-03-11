import type { CkpNodeType, NodeCategory, WorkflowTemplate } from "./types";

export const TYPE_ICONS: Record<string, string> = {
  sequence: "▶",
  logic: "◇",
  loop: "↻",
  parallel: "⫽",
  human_approval: "✋",
  llm_action: "🤖",
  processing: "⚙",
  verification: "✓",
  transform: "⇌",
  subflow: "↗",
  terminate: "⏹",
};

export const TYPE_BG: Record<string, string> = {
  sequence: "#3B82F6",
  processing: "#2563EB",
  transform: "#1D4ED8",
  subflow: "#60A5FA",
  llm_action: "#7C3AED",
  loop: "#F97316",
  parallel: "#EA580C",
  logic: "#F59E0B",
  verification: "#D97706",
  human_approval: "#EF4444",
  terminate: "#6B7280",
};

export const TYPE_THEME: Record<string, {
  accent: string;
  iconBg: string;
  tint: string;
  text: string;
  border: string;
}> = {
  sequence: { accent: "bg-blue-500", iconBg: "bg-blue-500", tint: "bg-blue-50", text: "text-blue-700", border: "border-blue-500" },
  logic: { accent: "bg-amber-500", iconBg: "bg-amber-500", tint: "bg-amber-50", text: "text-amber-700", border: "border-amber-500" },
  loop: { accent: "bg-violet-500", iconBg: "bg-violet-500", tint: "bg-violet-50", text: "text-violet-700", border: "border-violet-500" },
  parallel: { accent: "bg-cyan-500", iconBg: "bg-cyan-500", tint: "bg-cyan-50", text: "text-cyan-700", border: "border-cyan-500" },
  human_approval: { accent: "bg-red-500", iconBg: "bg-red-500", tint: "bg-red-50", text: "text-red-700", border: "border-red-500" },
  llm_action: { accent: "bg-emerald-500", iconBg: "bg-emerald-500", tint: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-500" },
  processing: { accent: "bg-indigo-500", iconBg: "bg-indigo-500", tint: "bg-indigo-50", text: "text-indigo-700", border: "border-indigo-500" },
  verification: { accent: "bg-orange-500", iconBg: "bg-orange-500", tint: "bg-orange-50", text: "text-orange-700", border: "border-orange-500" },
  transform: { accent: "bg-pink-500", iconBg: "bg-pink-500", tint: "bg-pink-50", text: "text-pink-700", border: "border-pink-500" },
  subflow: { accent: "bg-teal-500", iconBg: "bg-teal-500", tint: "bg-teal-50", text: "text-teal-700", border: "border-teal-500" },
  terminate: { accent: "bg-gray-500", iconBg: "bg-gray-500", tint: "bg-gray-100", text: "text-gray-700", border: "border-gray-500" },
};

export const DEFAULT_NODE_THEME = {
  accent: "bg-gray-400",
  iconBg: "bg-gray-400",
  tint: "bg-gray-100",
  text: "text-gray-700",
  border: "border-gray-400",
};

export const TYPE_CATEGORY: Record<string, NodeCategory> = {
  sequence: "deterministic",
  processing: "deterministic",
  transform: "deterministic",
  subflow: "deterministic",
  llm_action: "intelligent",
  loop: "control",
  parallel: "control",
  logic: "control",
  verification: "control",
  human_approval: "control",
  terminate: "control",
};

export const CATEGORY_META: Record<NodeCategory, { label: string; color: string; description: string; badge: string }> = {
  deterministic: {
    label: "Deterministic",
    color: "#3B82F6",
    description: "API calls, data operations, transforms, subflows",
    badge: "bg-blue-100 text-blue-700",
  },
  intelligent: {
    label: "Intelligent",
    color: "#7C3AED",
    description: "LLM actions, agents, AI reasoning",
    badge: "bg-purple-100 text-purple-700",
  },
  control: {
    label: "Control",
    color: "#F97316",
    description: "Logic, loops, approvals, human-in-the-loop",
    badge: "bg-orange-100 text-orange-700",
  },
};

export const CATEGORY_THEME: Record<NodeCategory, { bg: string; dot: string; text: string }> = {
  deterministic: { bg: "bg-blue-50", dot: "bg-blue-500", text: "text-blue-700" },
  intelligent: { bg: "bg-violet-50", dot: "bg-violet-500", text: "text-violet-700" },
  control: { bg: "bg-orange-50", dot: "bg-orange-500", text: "text-orange-700" },
};

export const NODE_PALETTE_GROUPS: Array<{ category: NodeCategory; types: CkpNodeType[] }> = [
  { category: "deterministic", types: ["sequence", "processing", "transform", "subflow"] },
  { category: "intelligent", types: ["llm_action"] },
  { category: "control", types: ["loop", "parallel", "logic", "verification", "human_approval", "terminate"] },
];

export const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    name: "Invoice Processing",
    description: "Extract fields, validate, then route to approval or rejection",
    icon: "🧾",
    workflowGraph: {
      start_node: "extract_fields",
      nodes: {
        extract_fields: { type: "llm_action", description: "Extract invoice fields via LLM", next_node: "validate_fields" },
        validate_fields: { type: "processing", description: "Validate extracted fields", on_pass: "request_approval", on_fail: "flag_invalid" },
        request_approval: { type: "human_approval", description: "Manager approves invoice", on_approve: "process_payment", on_reject: "flag_invalid" },
        process_payment: { type: "sequence", description: "POST to payment API", next_node: "done" },
        flag_invalid: { type: "sequence", description: "Log invalid invoice", next_node: "done" },
        done: { type: "terminate", status: "success" },
      },
    },
  },
  {
    name: "Customer Support",
    description: "Classify inquiry, route to specialist or auto-reply",
    icon: "💬",
    workflowGraph: {
      start_node: "classify_inquiry",
      nodes: {
        classify_inquiry: { type: "llm_action", description: "Classify customer inquiry type", next_node: "route" },
        route: { type: "logic", description: "Route by inquiry category", on_true: "auto_reply", on_false: "specialist_queue" },
        auto_reply: { type: "llm_action", description: "Generate and send auto reply", next_node: "done" },
        specialist_queue: { type: "sequence", description: "Enqueue for human specialist", next_node: "await_specialist" },
        await_specialist: { type: "human_approval", description: "Specialist resolves ticket", on_approve: "done", on_reject: "escalate" },
        escalate: { type: "sequence", description: "Escalate to senior support", next_node: "done" },
        done: { type: "terminate", status: "success" },
      },
    },
  },
  {
    name: "Contract Review",
    description: "Summarise, check compliance, flag risks, require sign-off",
    icon: "📄",
    workflowGraph: {
      start_node: "summarise",
      nodes: {
        summarise: { type: "llm_action", description: "Summarise contract clauses", next_node: "compliance_check" },
        compliance_check: { type: "llm_action", description: "Check against compliance rules", next_node: "risk_score" },
        risk_score: { type: "processing", description: "Compute risk score", on_pass: "legal_review", on_fail: "flag_risks" },
        flag_risks: { type: "sequence", description: "Log and notify risk owner", next_node: "legal_review" },
        legal_review: { type: "human_approval", description: "Legal signs off contract", on_approve: "archive", on_reject: "revise" },
        revise: { type: "sequence", description: "Send back for revision", next_node: "done" },
        archive: { type: "sequence", description: "Archive approved contract", next_node: "done" },
        done: { type: "terminate", status: "success" },
      },
    },
  },
  {
    name: "Agentic Orchestration",
    description: "Agent analyses input and dynamically picks the next step — no hard-coded routing",
    icon: "🧠",
    workflowGraph: {
      start_node: "ingest",
      nodes: {
        ingest: {
          type: "sequence",
          description: "Fetch and normalise input data",
          next_node: "agent_router",
        },
        agent_router: {
          type: "llm_action",
          description: "Analyse context and choose the best next action",
          model: "gpt-4o",
          orchestration_mode: true,
          branches: ["deep_analysis", "quick_summary", "escalate_human"],
          prompt: "Given the following data: {{vars.input}}\nDecide which action is most appropriate and return JSON with the field '_next_node'.",
          system_prompt: "You are a workflow orchestrator. Evaluate the inputs and select the best processing path.",
        },
        deep_analysis: {
          type: "llm_action",
          description: "Thorough multi-step analysis",
          next_node: "compile_report",
        },
        quick_summary: {
          type: "llm_action",
          description: "Fast high-level summary",
          next_node: "compile_report",
        },
        escalate_human: {
          type: "human_approval",
          description: "Needs human judgment — route to specialist",
          on_approve: "compile_report",
          on_reject: "compile_report",
        },
        compile_report: {
          type: "processing",
          description: "Compile final report",
          on_pass: "done",
          on_fail: "done",
        },
        done: { type: "terminate", status: "success" },
      },
    },
  },
];

export const EDGE_LABEL_OPTIONS = [
  { value: "", label: "→ next (default flow)" },
  { value: "approve", label: "✓ approve" },
  { value: "reject", label: "✕ reject" },
  { value: "timeout", label: "⏱ timeout" },
  { value: "true", label: "◎ true / yes" },
  { value: "false", label: "○ false / no" },
  { value: "default", label: "— default" },
  { value: "pass", label: "✓ pass" },
  { value: "fail", label: "✕ fail" },
  { value: "error", label: "⚠ error" },
  { value: "loop body", label: "↻ loop body" },
];