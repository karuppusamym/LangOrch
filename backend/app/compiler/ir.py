"""Internal Representation (IR) dataclasses — output of CKP compilation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Executor binding ────────────────────────────────────────────


@dataclass
class ExecutorBinding:
    kind: str  # "mcp_tool" | "agent_http" | "internal"
    ref: str | None = None  # tool name / agent endpoint
    mode: str = "step"  # "step" | "batch"


# ── Step ────────────────────────────────────────────────────────


@dataclass
class IRStep:
    step_id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int | None = None
    wait_ms: int | None = None
    wait_after_ms: int | None = None
    retry_on_failure: bool = False
    retry_config: dict[str, Any] | None = None  # per-step retry override
    output_variable: str | None = None
    idempotency_key: str | None = None
    executor_binding: ExecutorBinding | None = None


# ── Error handler ───────────────────────────────────────────────


@dataclass
class IRErrorHandler:
    error_type: str
    action: str  # "retry" | "screenshot_and_fail" | "fail" | "ignore" | "escalate"
    max_retries: int = 0
    delay_ms: int = 0
    retry_policy: dict[str, Any] | None = None
    recovery_steps: list[IRStep] = field(default_factory=list)
    fallback_node: str | None = None
    notify_on_error: bool = False


# ── Validation check ────────────────────────────────────────────


@dataclass
class IRValidation:
    id: str
    check: str
    condition: str | None = None
    expected_values: list[Any] | None = None
    on_failure: str = "throw_exception"
    message: str | None = None


# ── Type-specific payloads ──────────────────────────────────────


@dataclass
class IRSequencePayload:
    steps: list[IRStep] = field(default_factory=list)
    validations: list[IRValidation] = field(default_factory=list)
    error_handlers: list[IRErrorHandler] = field(default_factory=list)


@dataclass
class IRLogicRule:
    condition_expr: str
    next_node_id: str


@dataclass
class IRLogicPayload:
    rules: list[IRLogicRule] = field(default_factory=list)
    default_next_node_id: str | None = None


@dataclass
class IRLoopPayload:
    iterator_var: str = ""
    iterator_variable: str = ""
    index_variable: str | None = None
    body_node_id: str = ""
    collect_variable: str | None = None
    max_iterations: int | None = None
    continue_on_error: bool = False
    next_node_id: str | None = None


@dataclass
class IRParallelBranch:
    branch_id: str
    start_node_id: str


@dataclass
class IRParallelPayload:
    branches: list[IRParallelBranch] = field(default_factory=list)
    wait_strategy: str = "all"
    branch_failure: str = "continue"
    next_node_id: str | None = None


@dataclass
class IRProcessingOp:
    action: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class IRProcessingPayload:
    operations: list[IRProcessingOp] = field(default_factory=list)
    next_node_id: str | None = None


@dataclass
class IRVerificationCheck:
    id: str
    condition: str
    on_fail: str = "fail_workflow"
    message: str = ""


@dataclass
class IRVerificationPayload:
    checks: list[IRVerificationCheck] = field(default_factory=list)
    next_node_id: str | None = None


@dataclass
class IRLlmAttachment:
    type: str
    source: str
    description: str | None = None


@dataclass
class IRLlmActionPayload:
    prompt: str = ""
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int | None = None
    system_prompt: str | None = None
    json_mode: bool = False
    attachments: list[IRLlmAttachment] = field(default_factory=list)
    retry: dict[str, Any] | None = None
    outputs: dict[str, str] = field(default_factory=dict)
    next_node_id: str | None = None


@dataclass
class IRHumanApprovalPayload:
    prompt: str = ""
    decision_type: str = "approve_reject"
    options: list[str] | None = None
    timeout_ms: int | None = None
    timeout_action: str | None = None
    escalation_contact: str | None = None
    context_data: dict[str, Any] | None = None
    approval_level: str | None = None
    on_approve: str | None = None
    on_reject: str | None = None
    on_timeout: str | None = None


@dataclass
class IRTransformOp:
    type: str
    source_variable: str
    expression: str
    output_variable: str
    params: dict[str, Any] | None = None


@dataclass
class IRTransformPayload:
    transformations: list[IRTransformOp] = field(default_factory=list)
    next_node_id: str | None = None


@dataclass
class IRSubflowPayload:
    procedure_id: str = ""
    version: str | None = None
    input_mapping: dict[str, str] = field(default_factory=dict)
    output_mapping: dict[str, str] = field(default_factory=dict)
    on_failure: str = "fail_parent"
    inherit_context: bool = False
    next_node_id: str | None = None


@dataclass
class IRTerminatePayload:
    status: str = "success"
    cleanup_actions: list[IRProcessingOp] = field(default_factory=list)
    error_actions: list[IRProcessingOp] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)


# ── Node ────────────────────────────────────────────────────────


@dataclass
class IRNode:
    node_id: str
    type: str
    agent: str | None = None
    description: str | None = None
    is_checkpoint: bool = False
    next_node_id: str | None = None
    sla: dict[str, Any] | None = None
    telemetry: dict[str, Any] | None = None
    idempotency_key: str | None = None
    payload: Any = None  # one of the IR*Payload types above


# ── Procedure (top-level IR) ────────────────────────────────────


@dataclass
class IRProcedure:
    procedure_id: str
    version: str
    global_config: dict[str, Any] = field(default_factory=dict)
    variables_schema: dict[str, Any] = field(default_factory=dict)
    start_node_id: str = ""
    nodes: dict[str, IRNode] = field(default_factory=dict)
    provenance: dict[str, Any] | None = None
    retrieval_metadata: dict[str, Any] | None = None
