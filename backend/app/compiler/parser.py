"""CKP JSON parser — converts raw CKP dict into IR structures."""

from __future__ import annotations

from typing import Any

from app.compiler.ir import (
    ExecutorBinding,
    IRErrorHandler,
    IRHumanApprovalPayload,
    IRLlmActionPayload,
    IRLlmAttachment,
    IRLogicPayload,
    IRLogicRule,
    IRLoopPayload,
    IRNode,
    IRParallelBranch,
    IRParallelPayload,
    IRProcessingOp,
    IRProcessingPayload,
    IRProcedure,
    IRSequencePayload,
    IRStep,
    IRSubflowPayload,
    IRTerminatePayload,
    IRTransformOp,
    IRTransformPayload,
    IRValidation,
    IRVerificationCheck,
    IRVerificationPayload,
)


def parse_ckp(ckp: dict[str, Any]) -> IRProcedure:
    """Parse a CKP JSON dict into an IRProcedure."""

    wf = ckp.get("workflow_graph", {})
    nodes_raw = wf.get("nodes", {})

    nodes: dict[str, IRNode] = {}
    for nid, ndata in nodes_raw.items():
        nodes[nid] = _parse_node(nid, ndata)

    return IRProcedure(
        procedure_id=ckp["procedure_id"],
        version=ckp["version"],
        global_config=ckp.get("global_config", {}),
        variables_schema=ckp.get("variables_schema", {}),
        start_node_id=wf.get("start_node", ""),
        nodes=nodes,
        provenance=ckp.get("provenance"),
        retrieval_metadata=ckp.get("retrieval_metadata"),
    )


# ── Internal helpers ────────────────────────────────────────────


def _parse_node(nid: str, d: dict[str, Any]) -> IRNode:
    ntype = d.get("type", "sequence")
    payload = _parse_payload(ntype, d)

    return IRNode(
        node_id=nid,
        type=ntype,
        agent=d.get("agent"),
        description=d.get("description"),
        is_checkpoint=d.get("is_checkpoint", False),
        next_node_id=d.get("next_node"),
        sla=d.get("sla"),
        telemetry=d.get("telemetry"),
        idempotency_key=d.get("idempotency_key"),
        payload=payload,
    )


def _parse_payload(ntype: str, d: dict[str, Any]) -> Any:
    parsers = {
        "sequence": _parse_sequence,
        "logic": _parse_logic,
        "loop": _parse_loop,
        "parallel": _parse_parallel,
        "processing": _parse_processing,
        "verification": _parse_verification,
        "llm_action": _parse_llm_action,
        "human_approval": _parse_human_approval,
        "transform": _parse_transform,
        "subflow": _parse_subflow,
        "terminate": _parse_terminate,
    }
    parser = parsers.get(ntype)
    if parser:
        return parser(d)
    return None


def _parse_sequence(d: dict) -> IRSequencePayload:
    steps = [_parse_step(s) for s in d.get("steps", [])]
    validations = [
        IRValidation(
            id=v.get("id", ""),
            check=v.get("check", "custom"),
            condition=v.get("condition"),
            expected_values=v.get("expected_values"),
            on_failure=v.get("on_failure", "throw_exception"),
            message=v.get("message"),
        )
        for v in d.get("validations", [])
    ]
    error_handlers = [_parse_error_handler(eh) for eh in d.get("error_handlers", [])]
    return IRSequencePayload(steps=steps, validations=validations, error_handlers=error_handlers)


def _parse_step(s: dict) -> IRStep:
    # Collect all step params except known meta fields
    meta_keys = {
        "step_id", "action", "timeout_ms", "wait_ms", "wait_after_ms",
        "retry_on_failure", "output_variable", "screenshot_on_complete",
    }
    params = {k: v for k, v in s.items() if k not in meta_keys}

    return IRStep(
        step_id=s.get("step_id", ""),
        action=s.get("action", ""),
        params=params,
        timeout_ms=s.get("timeout_ms"),
        wait_ms=s.get("wait_ms"),
        wait_after_ms=s.get("wait_after_ms"),
        retry_on_failure=s.get("retry_on_failure", False),
        output_variable=s.get("output_variable"),
    )


def _parse_error_handler(eh: dict) -> IRErrorHandler:
    recovery = [_parse_step(rs) for rs in eh.get("recovery_steps", [])]
    return IRErrorHandler(
        error_type=eh.get("error_type", ""),
        action=eh.get("action", "fail"),
        max_retries=eh.get("max_retries", 0),
        delay_ms=eh.get("delay_ms", 0),
        retry_policy=eh.get("retry_policy"),
        recovery_steps=recovery,
        fallback_node=eh.get("fallback_node"),
        notify_on_error=eh.get("notify_on_error", False),
    )


def _parse_logic(d: dict) -> IRLogicPayload:
    rules = [
        IRLogicRule(condition_expr=r["condition"], next_node_id=r["next_node"])
        for r in d.get("rules", [])
    ]
    return IRLogicPayload(rules=rules, default_next_node_id=d.get("default_next_node"))


def _parse_loop(d: dict) -> IRLoopPayload:
    return IRLoopPayload(
        iterator_var=d.get("iterator", ""),
        iterator_variable=d.get("iterator_variable", ""),
        index_variable=d.get("index_variable"),
        body_node_id=d.get("body_node", ""),
        collect_variable=d.get("collect_variable"),
        max_iterations=d.get("max_iterations"),
        continue_on_error=d.get("continue_on_error", False),
        next_node_id=d.get("next_node"),
    )


def _parse_parallel(d: dict) -> IRParallelPayload:
    branches = [
        IRParallelBranch(branch_id=b["branch_id"], start_node_id=b["start_node"])
        for b in d.get("branches", [])
    ]
    return IRParallelPayload(
        branches=branches,
        wait_strategy=d.get("wait_strategy", "all"),
        branch_failure=d.get("branch_failure", "continue"),
        next_node_id=d.get("next_node"),
    )


def _parse_processing(d: dict) -> IRProcessingPayload:
    ops = [IRProcessingOp(action=o.get("action", ""), params=o) for o in d.get("operations", [])]
    return IRProcessingPayload(operations=ops, next_node_id=d.get("next_node"))


def _parse_verification(d: dict) -> IRVerificationPayload:
    checks = [
        IRVerificationCheck(
            id=c.get("id", ""),
            condition=c.get("condition", ""),
            on_fail=c.get("on_fail", "fail_workflow"),
            message=c.get("message", ""),
        )
        for c in d.get("checks", [])
    ]
    return IRVerificationPayload(checks=checks, next_node_id=d.get("next_node"))


def _parse_llm_action(d: dict) -> IRLlmActionPayload:
    attachments = [
        IRLlmAttachment(type=a["type"], source=a["source"], description=a.get("description"))
        for a in d.get("attachments", [])
    ]
    return IRLlmActionPayload(
        prompt=d.get("prompt", ""),
        model=d.get("model", "gpt-4"),
        temperature=d.get("temperature", 0.7),
        max_tokens=d.get("max_tokens"),
        system_prompt=d.get("system_prompt"),
        json_mode=bool(d.get("json_mode", False)),
        attachments=attachments,
        retry=d.get("retry"),
        outputs=d.get("outputs", {}),
        next_node_id=d.get("next_node"),
    )


def _parse_human_approval(d: dict) -> IRHumanApprovalPayload:
    return IRHumanApprovalPayload(
        prompt=d.get("prompt", ""),
        decision_type=d.get("decision_type", "approve_reject"),
        options=d.get("options"),
        timeout_ms=d.get("timeout_ms"),
        timeout_action=d.get("timeout_action"),
        escalation_contact=d.get("escalation_contact"),
        context_data=d.get("context_data"),
        approval_level=d.get("approval_level"),
        on_approve=d.get("on_approve"),
        on_reject=d.get("on_reject"),
        on_timeout=d.get("on_timeout"),
    )


def _parse_transform(d: dict) -> IRTransformPayload:
    transforms = [
        IRTransformOp(
            type=t["type"],
            source_variable=t["source_variable"],
            expression=t["expression"],
            output_variable=t["output_variable"],
            params=t.get("params"),
        )
        for t in d.get("transformations", [])
    ]
    return IRTransformPayload(transformations=transforms, next_node_id=d.get("next_node"))


def _parse_subflow(d: dict) -> IRSubflowPayload:
    return IRSubflowPayload(
        procedure_id=d.get("procedure_id", ""),
        version=d.get("version"),
        input_mapping=d.get("input_mapping", {}),
        output_mapping=d.get("output_mapping", {}),
        on_failure=d.get("on_failure", "fail_parent"),
        inherit_context=d.get("inherit_context", False),
        next_node_id=d.get("next_node"),
    )


def _parse_terminate(d: dict) -> IRTerminatePayload:
    cleanup = [IRProcessingOp(action=o.get("action", ""), params=o) for o in d.get("cleanup_actions", [])]
    errors = [IRProcessingOp(action=o.get("action", ""), params=o) for o in d.get("error_actions", [])]
    return IRTerminatePayload(
        status=d.get("status", "success"),
        cleanup_actions=cleanup,
        error_actions=errors,
        outputs=d.get("outputs", {}),
    )
