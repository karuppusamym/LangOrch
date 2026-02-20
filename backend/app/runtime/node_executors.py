"""Node executor functions — one per CKP node type.

Sequence nodes dispatch steps dynamically:
  - Internal actions (log, wait, set_variable…) run in-process.
  - External actions are resolved at runtime from the agent registry DB
    via executor_dispatch.resolve_executor / dispatch_to_agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from app.compiler.ir import (
    IRHumanApprovalPayload,
    IRLogicPayload,
    IRLoopPayload,
    IRNode,
    IRParallelPayload,
    IRProcessingPayload,
    IRSequencePayload,
    IRSubflowPayload,
    IRTerminatePayload,
    IRTransformPayload,
    IRVerificationPayload,
    IRLlmActionPayload,
)
from app.config import settings
from app.runtime.state import OrchestratorState
from app.templating.engine import render_template_dict, render_template_str
from app.templating.expressions import evaluate_condition
from app.runtime.hil import resolve_approval_next_node
from app.utils.run_cancel import is_cancelled as _is_cancelled, RunCancelledError
from app.utils.metrics import record_step_execution, record_step_timeout, record_retry_attempt

logger = logging.getLogger("langorch.runtime")

# Cost-per-1k-tokens for common LLM models (USD)
# Source: public pricing pages as of 2026-02. Adjust as needed.
_MODEL_COST_PER_1K: dict[str, dict[str, float]] = {
    "gpt-4": {"prompt": 0.03, "completion": 0.06},
    "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
    "gpt-4o": {"prompt": 0.005, "completion": 0.015},
    "gpt-3.5-turbo": {"prompt": 0.0005, "completion": 0.0015},
    "claude-3-opus": {"prompt": 0.015, "completion": 0.075},
    "claude-3-sonnet": {"prompt": 0.003, "completion": 0.015},
    "claude-3-haiku": {"prompt": 0.00025, "completion": 0.00125},
    "claude-3-5-sonnet": {"prompt": 0.003, "completion": 0.015},
}


def _get_retry_config(state: OrchestratorState) -> dict[str, Any]:
    """Extract retry configuration from state's global_config (set by execution_service).

    Priority order:
      state["global_config"]["retry_policy"]  (per-procedure)
      state["global_config"]                  (top-level shortcuts)
      hard-coded defaults
    """
    gc: dict[str, Any] = state.get("global_config") or {}
    rc: dict[str, Any] = gc.get("retry_policy") or {}
    return {
        "max_retries":        int(rc.get("max_retries")        or gc.get("max_retries")        or 3),
        "retry_delay_ms":     int(rc.get("retry_delay_ms")     or rc.get("delay_ms")           or gc.get("retry_delay_ms")   or 1000),
        "backoff_multiplier": float(rc.get("backoff_multiplier") or gc.get("backoff_multiplier") or 2.0),
    }


def _get_step_retry_config(step: Any, state: OrchestratorState) -> dict[str, Any]:
    """Merge step-level retry override with the global retry policy.

    Step-level retry config is stored in ``step.retry_config`` (a dict with
    ``max_retries`` / ``retry_delay_ms`` / ``backoff_multiplier`` keys).
    Any key not present in the step config falls back to the global policy.
    """
    global_cfg = _get_retry_config(state)
    step_rc: dict[str, Any] = getattr(step, "retry_config", None) or {}
    if not step_rc:
        return global_cfg
    return {
        "max_retries":        int(step_rc.get("max_retries")        or global_cfg["max_retries"]),
        "retry_delay_ms":     int(step_rc.get("retry_delay_ms")     or step_rc.get("delay_ms") or global_cfg["retry_delay_ms"]),
        "backoff_multiplier": float(step_rc.get("backoff_multiplier") or global_cfg["backoff_multiplier"]),
    }


async def execute_sequence(
    node: IRNode, state: OrchestratorState, db_factory: Callable | None = None
) -> OrchestratorState:
    """Execute all steps in a sequence node and return updated state.

    For each step:
      1. If the step is bound as internal → run it locally.
      2. If unbound → resolve from agent registry DB → dispatch over HTTP.
    """
    from app.runtime.executor_dispatch import (
        resolve_executor,
        dispatch_to_agent,
        dispatch_to_mcp,
    )
    from app.services import run_service
    from app.utils.redaction import redact_sensitive_data

    payload: IRSequencePayload = node.payload
    vs = dict(state.get("vars", {}))
    run_id = state.get("run_id", "")

    # Rate limiting: honour global_config.rate_limiting.max_concurrent if a semaphore is in state
    _rate_sem = (state.get("global_config") or {}).get("_rate_semaphore")

    # SLA tracking: record node start time to check sla.max_duration_ms
    import time as _time_mod
    _node_start_wall = _time_mod.monotonic()
    _sla_max_ms: int | None = None
    if node.sla and isinstance(node.sla, dict):
        _sla_max_ms = node.sla.get("max_duration_ms")

    for step in payload.steps:
        if run_id and _is_cancelled(run_id):
            raise RunCancelledError(f"Run {run_id} was cancelled")
        rendered_params = render_template_dict(step.params, vs)
        # Redact sensitive fields before logging
        safe_params = redact_sensitive_data(rendered_params)
        logger.info("Step %s: action=%s params=%s", step.step_id, step.action, safe_params)

        # wait_ms: pause before this step executes
        if step.wait_ms and isinstance(step.wait_ms, (int, float)) and step.wait_ms > 0:
            logger.debug("Step %s: waiting %dms before execution", step.step_id, step.wait_ms)
            await asyncio.sleep(step.wait_ms / 1000.0)

        # Retry loop configuration — step-level override wins over global policy
        retry_config = _get_step_retry_config(step, state)
        max_retries = retry_config.get("max_retries", 0)
        attempt = 0
        _step_start_time = __import__('time').monotonic()
        
        while True:
            result: Any = None
            used_cached_result = False

            if db_factory is not None and run_id:
                async with db_factory() as db:
                    cached_result = await _get_completed_step_result(db, run_id, node.node_id, step.step_id)
                    if cached_result is not None:
                        result = cached_result
                        used_cached_result = True
                        logger.info(
                            "Step %s/%s reused cached idempotent result",
                            node.node_id,
                            step.step_id,
                        )
                    else:
                        await run_service.emit_event(
                            db,
                            run_id,
                            "step_started",
                            node_id=node.node_id,
                            step_id=step.step_id,
                            payload={"action": step.action},
                        )
                        # Evaluate idempotency_key template against current vars
                        rendered_idem_key = (
                            render_template_str(step.idempotency_key, vs)
                            if step.idempotency_key
                            else None
                        )
                        await _mark_step_started(
                            db,
                            run_id,
                            node.node_id,
                            step.step_id,
                            rendered_idem_key,
                        )
                    await db.commit()

            if used_cached_result:
                if step.output_variable and result is not None:
                    vs[step.output_variable] = result

                if db_factory is not None and run_id:
                    async with db_factory() as db:
                        await run_service.emit_event(
                            db,
                            run_id,
                            "step_completed",
                            node_id=node.node_id,
                            step_id=step.step_id,
                            payload={
                                "action": step.action,
                                "output_variable": step.output_variable,
                                "cached": True,
                            },
                        )
                        await db.commit()
                record_step_execution(node.node_id, "cached")
                break  # Exit retry loop, continue to next step

            try:
                # Fast path: internal actions
                if step.executor_binding and step.executor_binding.kind == "internal":
                    _internal_coro = _execute_step_action(step.action, rendered_params, vs)
                    if step.timeout_ms and step.timeout_ms > 0:
                        try:
                            result = await asyncio.wait_for(
                                _internal_coro, timeout=step.timeout_ms / 1000.0
                            )
                        except asyncio.TimeoutError:
                            record_step_timeout(node.node_id, step.step_id, step.timeout_ms)
                            if db_factory is not None and run_id:
                                async with db_factory() as db:
                                    await run_service.emit_event(
                                        db, run_id, "step_timeout",
                                        node_id=node.node_id, step_id=step.step_id,
                                        payload={"timeout_ms": step.timeout_ms, "action": step.action},
                                    )
                                    await db.commit()
                            raise TimeoutError(
                                f"Step {step.step_id} timed out after {step.timeout_ms}ms"
                            )
                    else:
                        result = await _internal_coro
                elif db_factory is not None:
                    # Dynamic resolution from agent registry
                    async with db_factory() as db:
                        binding = await resolve_executor(db, node, step)

                    # dry_run: skip external agent/MCP dispatch; emit a dry_run_step_skipped event
                    _exec_mode = state.get("execution_mode", "production")
                    _global_cfg_rt = state.get("global_config") or {}
                    _mock_external = _global_cfg_rt.get("mock_external_calls", False)
                    _test_overrides = _global_cfg_rt.get("test_data_overrides") or {}
                    if _exec_mode == "dry_run" and binding.kind in ("agent_http", "mcp_tool"):
                        logger.info(
                            "dry_run: skipping %s dispatch for step %s/%s (binding=%s)",
                            binding.kind, node.node_id, step.step_id, binding.ref,
                        )
                        result = {"dry_run": True, "skipped_action": step.action, "binding": binding.kind}
                        if db_factory is not None and run_id:
                            async with db_factory() as db:
                                await run_service.emit_event(
                                    db, run_id, "dry_run_step_skipped",
                                    node_id=node.node_id, step_id=step.step_id,
                                    payload={
                                        "action": step.action,
                                        "binding": binding.kind,
                                        "ref": binding.ref,
                                    },
                                )
                                await db.commit()
                    elif step.step_id in _test_overrides:
                        # test_data_overrides: return configured test result for this step
                        result = _test_overrides[step.step_id]
                        logger.info(
                            "test_data_overrides: returning override for step %s/%s",
                            node.node_id, step.step_id,
                        )
                        if db_factory is not None and run_id:
                            async with db_factory() as db:
                                await run_service.emit_event(
                                    db, run_id, "step_test_override_applied",
                                    node_id=node.node_id, step_id=step.step_id,
                                    payload={"step_id": step.step_id, "override": result},
                                )
                                await db.commit()
                    elif _mock_external and binding.kind in ("agent_http", "mcp_tool"):
                        # mock_external_calls: return stub result without calling real agent/MCP
                        logger.info(
                            "mock_external_calls: returning stub for step %s/%s (binding=%s)",
                            node.node_id, step.step_id, binding.kind,
                        )
                        result = {"mocked": True, "action": step.action, "binding": binding.kind}
                        if db_factory is not None and run_id:
                            async with db_factory() as db:
                                await run_service.emit_event(
                                    db, run_id, "step_mock_applied",
                                    node_id=node.node_id, step_id=step.step_id,
                                    payload={"action": step.action, "binding": binding.kind, "ref": binding.ref},
                                )
                                await db.commit()
                    elif binding.kind == "internal":
                        _dyn_internal_coro = _execute_step_action(step.action, rendered_params, vs)
                        if step.timeout_ms and step.timeout_ms > 0:
                            try:
                                result = await asyncio.wait_for(
                                    _dyn_internal_coro, timeout=step.timeout_ms / 1000.0
                                )
                            except asyncio.TimeoutError:
                                record_step_timeout(node.node_id, step.step_id, step.timeout_ms)
                                if db_factory is not None and run_id:
                                    async with db_factory() as db:
                                        await run_service.emit_event(
                                            db, run_id, "step_timeout",
                                            node_id=node.node_id, step_id=step.step_id,
                                            payload={"timeout_ms": step.timeout_ms, "action": step.action, "binding": "internal"},
                                        )
                                        await db.commit()
                                raise TimeoutError(
                                    f"Step {step.step_id} timed out after {step.timeout_ms}ms"
                                )
                        else:
                            result = await _dyn_internal_coro
                    elif binding.kind == "agent_http":
                        lease_id: str | None = None
                        if run_id and binding.ref:
                            async with db_factory() as db:
                                lease_id = await _acquire_agent_lease(
                                    db,
                                    agent_url=binding.ref,
                                    run_id=run_id,
                                    node_id=node.node_id,
                                    step_id=step.step_id,
                                )
                                await db.commit()

                        try:
                            _dispatch_coro = dispatch_to_agent(
                                agent_url=binding.ref,
                                action=step.action,
                                params=rendered_params,
                                run_id=run_id,
                                node_id=node.node_id,
                                step_id=step.step_id,
                            )
                            if step.timeout_ms and step.timeout_ms > 0:
                                try:
                                    result = await asyncio.wait_for(
                                        _dispatch_coro, timeout=step.timeout_ms / 1000.0
                                    )
                                except asyncio.TimeoutError:
                                    record_step_timeout(node.node_id, step.step_id, step.timeout_ms)
                                    if db_factory is not None and run_id:
                                        async with db_factory() as db:
                                            await run_service.emit_event(
                                                db, run_id, "step_timeout",
                                                node_id=node.node_id, step_id=step.step_id,
                                                payload={"timeout_ms": step.timeout_ms, "action": step.action, "binding": "agent_http"},
                                            )
                                            await db.commit()
                                    raise TimeoutError(
                                        f"Step {step.step_id} timed out after {step.timeout_ms}ms"
                                    )
                            else:
                                result = await _dispatch_coro
                        finally:
                            if lease_id and db_factory is not None:
                                async with db_factory() as db:
                                    await _release_lease(db, lease_id)
                                    await db.commit()
                    elif binding.kind == "mcp_tool":
                        _mcp_coro = dispatch_to_mcp(
                            mcp_url=binding.ref,
                            tool_name=step.action,
                            arguments=rendered_params,
                            run_id=run_id,
                            node_id=node.node_id,
                            step_id=step.step_id,
                        )
                        if step.timeout_ms and step.timeout_ms > 0:
                            try:
                                result = await asyncio.wait_for(
                                    _mcp_coro, timeout=step.timeout_ms / 1000.0
                                )
                            except asyncio.TimeoutError:
                                record_step_timeout(node.node_id, step.step_id, step.timeout_ms)
                                if db_factory is not None and run_id:
                                    async with db_factory() as db:
                                        await run_service.emit_event(
                                            db, run_id, "step_timeout",
                                            node_id=node.node_id, step_id=step.step_id,
                                            payload={"timeout_ms": step.timeout_ms, "action": step.action, "binding": "mcp_tool"},
                                        )
                                        await db.commit()
                                raise TimeoutError(
                                    f"Step {step.step_id} timed out after {step.timeout_ms}ms"
                                )
                        else:
                            result = await _mcp_coro
                    else:
                        logger.warning("Unsupported binding kind '%s' for step %s", binding.kind, step.step_id)
                        result = {"action": step.action, "params": rendered_params}
                else:
                    # No db_factory — fallback to internal handler (dev/test mode)
                    logger.warning("No db_factory available; falling back to internal handler for step %s", step.step_id)
                    result = await _execute_step_action(step.action, rendered_params, vs)
                
                # Execution succeeded - exit retry loop
                record_step_execution(node.node_id, "completed")
                break
                
            except Exception as exc:
                # Apply retry policy if enabled
                if step.retry_on_failure and attempt < max_retries:
                    delay_ms = retry_config.get("retry_delay_ms", 1000)
                    multiplier = retry_config.get("backoff_multiplier", 2.0)
                    actual_delay = delay_ms * (multiplier ** attempt) / 1000.0
                    
                    # Record retry attempt
                    record_retry_attempt(node.node_id, step.step_id)
                    
                    logger.warning(
                        "Step %s/%s failed (attempt %d/%d), retrying after %.2fs: %s",
                        node.node_id,
                        step.step_id,
                        attempt + 1,
                        max_retries,
                        actual_delay,
                        exc,
                    )
                    await asyncio.sleep(actual_delay)
                    attempt += 1
                    continue  # Retry the step (continue while loop)
                
                # Final failure after retries exhausted or retry not enabled
                record_step_execution(node.node_id, "failed")
                if db_factory is not None and run_id:
                    async with db_factory() as db:
                        await _mark_step_failed(db, run_id, node.node_id, step.step_id)
                        await db.commit()
                # screenshot_on_fail: emit screenshot_requested event if global_config flag is set
                _screenshot_flag = (state.get("global_config") or {}).get("screenshot_on_fail", False)
                if _screenshot_flag and db_factory is not None and run_id:
                    try:
                        async with db_factory() as _sdb:
                            await run_service.emit_event(
                                _sdb, run_id, "screenshot_requested",
                                node_id=node.node_id, step_id=step.step_id,
                                payload={"reason": "screenshot_on_fail", "error": str(exc)},
                            )
                            await _sdb.commit()
                    except Exception:
                        logger.warning("Failed to emit screenshot_requested event", exc_info=True)
                # Check error_handlers for a matching handler
                _eh_matched = False
                _eh_retry_step = False
                for _eh in (getattr(payload, "error_handlers", None) or []):
                    _et = getattr(_eh, "error_type", None)
                    if _et and _et not in (type(exc).__name__,):
                        continue
                    _eh_matched = True
                    _eh_action = (getattr(_eh, "action", None) or "ignore").lower()

                    # Execute recovery steps first (regardless of action)
                    for _rs in (getattr(_eh, "recovery_steps", None) or []):
                        _rs_rendered = render_template_dict(_rs.params or {}, vs)
                        await _execute_step_action(_rs.action, _rs_rendered, vs)

                    # notify_on_error: emit a step_error_notification event + fire alert webhook
                    if getattr(_eh, "notify_on_error", False):
                        if db_factory is not None and run_id:
                            try:
                                async with db_factory() as _ndb:
                                    await run_service.emit_event(
                                        _ndb,
                                        run_id,
                                        "step_error_notification",
                                        node_id=node.node_id,
                                        step_id=step.step_id,
                                        payload={
                                            "error_type": _et,
                                            "error": str(exc),
                                            "handler_action": _eh_action,
                                        },
                                    )
                                    await _ndb.commit()
                            except Exception:  # never abort handler logic
                                logger.warning("notify_on_error: failed to emit event", exc_info=True)
                        try:
                            from app.services.execution_service import _fire_alert_webhook  # noqa: PLC0415
                            asyncio.ensure_future(_fire_alert_webhook(run_id or "", exc))
                        except Exception:
                            logger.warning("notify_on_error: failed to fire alert webhook", exc_info=True)

                    # action: "retry" — apply handler's own retry policy
                    if _eh_action == "retry":
                        _eh_max = int(getattr(_eh, "max_retries", 0) or 0)
                        _eh_delay = int(getattr(_eh, "delay_ms", 1000) or 1000)
                        if attempt < _eh_max:
                            record_retry_attempt(node.node_id, step.step_id)
                            await asyncio.sleep(_eh_delay / 1000.0)
                            attempt += 1
                            _eh_retry_step = True
                            break
                        raise  # handler retries exhausted

                    # action: "screenshot_and_fail" — log then re-raise
                    if _eh_action == "screenshot_and_fail":
                        logger.warning(
                            "screenshot_and_fail: step %s/%s",
                            node.node_id, step.step_id,
                        )
                        raise

                    # action: "fail" — re-raise
                    if _eh_action == "fail":
                        raise

                    # action: "escalate" or "ignore" — route via fallback_node or suppress
                    if getattr(_eh, "fallback_node", None):
                        _fb_state = dict(state)
                        _fb_state["vars"] = vs
                        _fb_state["next_node_id"] = _eh.fallback_node
                        _fb_state["current_node_id"] = node.node_id
                        return _fb_state  # type: ignore[return-value]

                    # "ignore" — suppress error, null-out output var
                    if step.output_variable:
                        vs[step.output_variable] = None
                    break

                if not _eh_matched:
                    raise  # no handler matched
                if _eh_retry_step:
                    continue  # restart while loop to retry the step
                break  # handler suppressed error; move to next step

        if step.output_variable and result is not None:
            vs[step.output_variable] = result

        if db_factory is not None and run_id and result is not None:
            artifacts = _extract_artifacts_from_result(result)
            if artifacts:
                async with db_factory() as db:
                    for artifact in artifacts:
                        kind = str(artifact.get("kind") or "artifact")
                        uri = artifact.get("uri")
                        if not isinstance(uri, str) or not uri:
                            continue
                        created = await run_service.create_artifact(
                            db,
                            run_id=run_id,
                            node_id=node.node_id,
                            step_id=step.step_id,
                            kind=kind,
                            uri=uri,
                        )
                        await run_service.emit_event(
                            db,
                            run_id,
                            "artifact_created",
                            node_id=node.node_id,
                            step_id=step.step_id,
                            payload={
                                "artifact_id": created.artifact_id,
                                "kind": created.kind,
                                "uri": created.uri,
                            },
                        )
                    await db.commit()

        if db_factory is not None and run_id:
            async with db_factory() as db:
                _step_duration_ms = int((__import__('time').monotonic() - _step_start_time) * 1000)
                _node_telemetry = node.telemetry or {}
                _telemetry_payload: dict = {
                    "action": step.action,
                    "output_variable": step.output_variable,
                    "cached": False,
                }
                if _node_telemetry.get("track_duration"):
                    _telemetry_payload["duration_ms"] = _step_duration_ms
                if _node_telemetry.get("track_retries") and attempt > 0:
                    _telemetry_payload["retry_count"] = attempt
                await _mark_step_completed(db, run_id, node.node_id, step.step_id, result)
                await run_service.emit_event(
                    db,
                    run_id,
                    "step_completed",
                    node_id=node.node_id,
                    step_id=step.step_id,
                    payload=_telemetry_payload,
                )
                await db.commit()

        # wait_after_ms: pause after this step completes
        if step.wait_after_ms and isinstance(step.wait_after_ms, (int, float)) and step.wait_after_ms > 0:
            logger.debug("Step %s: waiting %dms after execution", step.step_id, step.wait_after_ms)
            await asyncio.sleep(step.wait_after_ms / 1000.0)

    # SLA check: emit sla_breached event if node took longer than sla.max_duration_ms
    if _sla_max_ms and _sla_max_ms > 0:
        _node_duration_ms = int((_time_mod.monotonic() - _node_start_wall) * 1000)
        if _node_duration_ms > _sla_max_ms:
            logger.warning(
                "SLA breached: node %s took %dms (max %dms)",
                node.node_id, _node_duration_ms, _sla_max_ms,
            )
            if db_factory is not None and run_id:
                async with db_factory() as db:
                    await run_service.emit_event(
                        db, run_id, "sla_breached",
                        node_id=node.node_id,
                        payload={
                            "max_duration_ms": _sla_max_ms,
                            "actual_duration_ms": _node_duration_ms,
                            "on_breach": (node.sla or {}).get("on_breach", "log"),
                        },
                    )
                    await db.commit()

    state_out = dict(state)
    state_out["vars"] = vs
    state_out["next_node_id"] = node.next_node_id
    state_out["current_node_id"] = node.node_id
    return state_out  # type: ignore[return-value]


def execute_logic(node: IRNode, state: OrchestratorState) -> OrchestratorState:
    """Evaluate logic rules and route to the matching next_node."""
    payload: IRLogicPayload = node.payload
    vs = state.get("vars", {})

    for rule in payload.rules:
        expr = render_template_str(rule.condition_expr, vs)
        if evaluate_condition(expr, vs):
            return {**state, "next_node_id": rule.next_node_id, "current_node_id": node.node_id}  # type: ignore

    return {**state, "next_node_id": payload.default_next_node_id, "current_node_id": node.node_id}  # type: ignore


def execute_loop(node: IRNode, state: OrchestratorState) -> OrchestratorState:
    """Set up or advance loop iteration."""
    payload: IRLoopPayload = node.payload
    vs = dict(state.get("vars", {}))

    iterator = vs.get(payload.iterator_var, [])
    index = state.get("loop_index", 0)

    if index < len(iterator):
        item = iterator[index]
        vs[payload.iterator_variable] = item
        if payload.index_variable:
            vs[payload.index_variable] = index

        return {
            **state,
            "vars": vs,
            "loop_index": index,
            "loop_item": item,
            "next_node_id": payload.body_node_id,
            "current_node_id": node.node_id,
        }  # type: ignore

    # Loop complete
    return {
        **state,
        "vars": vs,
        "loop_index": 0,
        "next_node_id": payload.next_node_id,
        "current_node_id": node.node_id,
    }  # type: ignore


async def execute_parallel(
    node: IRNode,
    state: OrchestratorState,
    db_factory: Callable | None = None,
    nodes: dict[str, IRNode] | None = None,
) -> OrchestratorState:
    """Execute parallel branches and merge branch deltas into state vars."""
    payload: IRParallelPayload = node.payload
    base_vars = dict(state.get("vars", {}))

    if not payload.branches:
        return {
            **state,
            "next_node_id": payload.next_node_id,
            "current_node_id": node.node_id,
        }  # type: ignore

    if not nodes:
        return {
            **state,
            "error": {
                "message": "Parallel node execution requires workflow nodes context",
                "node_id": node.node_id,
            },
            "terminal_status": "failed",
            "next_node_id": None,
            "current_node_id": node.node_id,
        }  # type: ignore

    branch_deltas: dict[str, dict[str, Any]] = {}
    branch_errors: dict[str, Any] = {}
    wait_strategy = (payload.wait_strategy or "all").lower()
    branch_failure = (payload.branch_failure or "continue").lower()

    for branch in payload.branches:
        branch_state: OrchestratorState = {
            **state,
            "vars": dict(base_vars),
            "current_node_id": branch.start_node_id,
            "next_node_id": branch.start_node_id,
            "error": None,
            "terminal_status": None,
        }

        branch_final = await _execute_branch_path(
            start_node_id=branch.start_node_id,
            join_node_id=payload.next_node_id,
            state=branch_state,
            nodes=nodes,
            db_factory=db_factory,
        )

        branch_deltas[branch.branch_id] = _compute_var_delta(base_vars, branch_final.get("vars", {}))

        if branch_final.get("terminal_status") == "awaiting_approval":
            return {
                **branch_final,
                "current_node_id": node.node_id,
                "next_node_id": None,
            }  # type: ignore

        if branch_final.get("error"):
            branch_errors[branch.branch_id] = branch_final.get("error")
            if branch_failure == "fail":
                return {
                    **state,
                    "vars": base_vars,
                    "error": {
                        "message": f"Parallel branch '{branch.branch_id}' failed",
                        "node_id": node.node_id,
                        "branch_error": branch_final.get("error"),
                    },
                    "terminal_status": "failed",
                    "next_node_id": None,
                    "current_node_id": node.node_id,
                }  # type: ignore

        if wait_strategy == "any" and not branch_final.get("error"):
            break

    merged_vars = dict(base_vars)
    for delta in branch_deltas.values():
        merged_vars.update(delta)

    merged_vars["parallel_results"] = {
        "branches": branch_deltas,
        "errors": branch_errors,
    }

    return {
        **state,
        "vars": merged_vars,
        "next_node_id": payload.next_node_id,
        "current_node_id": node.node_id,
    }  # type: ignore


def execute_verification(node: IRNode, state: OrchestratorState) -> OrchestratorState:
    """Evaluate verification checks."""
    payload: IRVerificationPayload = node.payload
    vs = state.get("vars", {})

    for check in payload.checks:
        expr = render_template_str(check.condition, vs)
        if not evaluate_condition(expr, vs):
            if check.on_fail == "fail_workflow":
                return {
                    **state,
                    "error": {"message": check.message, "node_id": node.node_id, "check_id": check.id},
                    "terminal_status": "failed",
                    "next_node_id": None,
                    "current_node_id": node.node_id,
                }  # type: ignore
            logger.warning("Verification warning: %s", check.message)

    return {**state, "next_node_id": payload.next_node_id, "current_node_id": node.node_id}  # type: ignore


def execute_processing(node: IRNode, state: OrchestratorState) -> OrchestratorState:
    """Execute processing operations (set_variable, log, etc.)."""
    payload: IRProcessingPayload = node.payload
    vs = dict(state.get("vars", {}))

    for op in payload.operations:
        rendered = render_template_dict(op.params, vs)
        result = _execute_internal_action(op.action, rendered, vs)
        output_var = rendered.get("output_variable")
        if output_var and result is not None:
            vs[output_var] = result

    return {**state, "vars": vs, "next_node_id": payload.next_node_id, "current_node_id": node.node_id}  # type: ignore


def execute_transform(node: IRNode, state: OrchestratorState) -> OrchestratorState:
    """Execute transform operations (filter, map, aggregate, etc.)."""
    payload: IRTransformPayload = node.payload
    vs = dict(state.get("vars", {}))

    for t in payload.transformations:
        source = vs.get(t.source_variable, [])
        vs[t.output_variable] = _execute_transform_op(
            op_type=t.type,
            source=source,
            expression=t.expression,
            params=t.params or {},
            vars_ctx=vs,
        )

    return {**state, "vars": vs, "next_node_id": payload.next_node_id, "current_node_id": node.node_id}  # type: ignore


def execute_human_approval(node: IRNode, state: OrchestratorState) -> OrchestratorState:
    """Pause for approval unless a prior decision is injected in run input vars.

    Decision injection format:
      vars.__approval_decisions[node_id] = "approved" | "rejected" | "timeout"
    """
    payload: IRHumanApprovalPayload = node.payload
    vs = dict(state.get("vars", {}))
    decisions = vs.get("__approval_decisions", {}) if isinstance(vs.get("__approval_decisions"), dict) else {}
    existing_decision = decisions.get(node.node_id)

    if existing_decision:
        next_node = resolve_approval_next_node(node, str(existing_decision))
        return {
            **state,
            "vars": vs,
            "approval_decision": str(existing_decision),
            "current_node_id": node.node_id,
            "next_node_id": next_node,
        }  # type: ignore

    approval_request = {
        "run_id": state.get("run_id"),
        "node_id": node.node_id,
        "prompt": payload.prompt,
        "decision_type": payload.decision_type,
        "options": payload.options,
        "context_data": payload.context_data,
    }

    return {
        **state,
        "vars": vs,
        "awaiting_approval": approval_request,
        "terminal_status": "awaiting_approval",
        "current_node_id": node.node_id,
        "next_node_id": None,  # will be set after approval decision
    }  # type: ignore


async def execute_llm_action(node: IRNode, state: OrchestratorState, db_factory: Callable | None = None) -> OrchestratorState:
    """Execute LLM action via OpenAI-compatible chat completion API."""
    from app.connectors.llm_client import LLMCallError, LLMClient

    payload: IRLlmActionPayload = node.payload
    vs = dict(state.get("vars", {}))
    prompt = render_template_str(payload.prompt, vs)
    logger.info("LLM action: model=%s prompt=%s", payload.model, prompt[:100])

    # Build node-level retry config: payload.retry overrides global policy
    global_cfg = _get_retry_config(state)
    node_retry: dict[str, Any] = payload.retry or {}
    max_retries = int(node_retry.get("max_retries") or global_cfg["max_retries"])
    retry_delay_ms = int(node_retry.get("retry_delay_ms") or node_retry.get("delay_ms") or global_cfg["retry_delay_ms"])
    backoff_multiplier = float(node_retry.get("backoff_multiplier") or global_cfg["backoff_multiplier"])

    attempt = 0
    last_exc: Exception | None = None
    while True:
        try:
            llm_result = await asyncio.to_thread(
                LLMClient().complete,
                prompt=prompt,
                model=payload.model,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                system_prompt=payload.system_prompt,
                json_mode=payload.json_mode,
            )
            last_exc = None
            break
        except LLMCallError as exc:
            last_exc = exc
            if attempt < max_retries:
                delay_s = retry_delay_ms * (backoff_multiplier ** attempt) / 1000.0
                logger.warning(
                    "LLM action node %s failed (attempt %d/%d), retrying in %.2fs: %s",
                    node.node_id, attempt + 1, max_retries, delay_s, exc,
                )
                record_retry_attempt(node.node_id, node.node_id)
                await asyncio.sleep(delay_s)
                attempt += 1
            else:
                break

    if last_exc:
        return {
            **state,
            "error": {"message": str(last_exc), "node_id": node.node_id},
            "terminal_status": "failed",
            "next_node_id": None,
            "current_node_id": node.node_id,
        }  # type: ignore

    # ── Token tracking ──────────────────────────────────────────
    usage = llm_result.get("usage", {})
    prompt_tokens: int = usage.get("prompt_tokens", 0)
    completion_tokens: int = usage.get("completion_tokens", 0)
    if (prompt_tokens or completion_tokens) and db_factory:
        try:
            from sqlalchemy import select as _select
            from app.db.models import Run as _Run
            run_id = state.get("run_id", "")
            async with db_factory() as _db:
                _res = await _db.execute(_select(_Run).where(_Run.run_id == run_id))
                _run = _res.scalar_one_or_none()
                if _run:
                    _run.total_prompt_tokens = (_run.total_prompt_tokens or 0) + prompt_tokens
                    _run.total_completion_tokens = (_run.total_completion_tokens or 0) + completion_tokens
                    # Estimate cost based on per-model rates
                    _model_key = (usage.get("model") or payload.model or "").lower().split("/")[-1]
                    _rates = _MODEL_COST_PER_1K.get(_model_key) or _MODEL_COST_PER_1K.get("gpt-4")
                    _cost = (
                        prompt_tokens * _rates["prompt"]
                        + completion_tokens * _rates["completion"]
                    ) / 1000.0
                    _run.estimated_cost_usd = (_run.estimated_cost_usd or 0.0) + _cost
                    await _db.commit()
                from app.services import run_service
                await run_service.emit_event(
                    _db, run_id, "llm_usage",
                    node_id=node.node_id,
                    payload={
                        "model": usage.get("model", payload.model),
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": usage.get("total_tokens", prompt_tokens + completion_tokens),
                    },
                )
        except Exception as _tok_exc:
            logger.warning("Failed to persist LLM token usage: %s", _tok_exc)

    text = llm_result.get("text", "")
    for key, mapping in payload.outputs.items():
        if mapping in ("text", "raw", "content"):
            vs[key] = text
        elif isinstance(mapping, str) and mapping.startswith("json:"):
            try:
                obj = json.loads(text)
                vs[key] = obj.get(mapping.split(":", 1)[1])
            except Exception:
                vs[key] = text
        else:
            vs[key] = text

    if not payload.outputs:
        vs["llm_output"] = text

    return {**state, "vars": vs, "next_node_id": payload.next_node_id, "current_node_id": node.node_id}  # type: ignore


async def execute_subflow(
    node: IRNode,
    state: OrchestratorState,
    db_factory: Callable | None = None,
) -> OrchestratorState:
    """Execute a child procedure as a subflow and merge mapped outputs."""
    from app.compiler.binder import bind_executors
    from app.compiler.parser import parse_ckp
    from app.compiler.validator import validate_ir
    from app.runtime.graph_builder import build_graph
    from app.services import procedure_service, run_service

    payload: IRSubflowPayload = node.payload
    vs = dict(state.get("vars", {}))
    run_id = state.get("run_id", "")

    if not db_factory:
        return {
            **state,
            "error": {
                "message": "Subflow execution requires db_factory",
                "node_id": node.node_id,
            },
            "terminal_status": "failed",
            "next_node_id": None,
            "current_node_id": node.node_id,
        }  # type: ignore

    child_vars = dict(vs) if payload.inherit_context else {}
    for child_key, parent_value in (payload.input_mapping or {}).items():
        if isinstance(parent_value, str):
            if parent_value in vs:
                child_vars[child_key] = vs.get(parent_value)
            else:
                child_vars[child_key] = render_template_str(parent_value, vs)
        else:
            child_vars[child_key] = parent_value

    async with db_factory() as db:
        child_proc = await procedure_service.get_procedure(db, payload.procedure_id, payload.version)
        if not child_proc:
            return {
                **state,
                "error": {
                    "message": f"Subflow procedure not found: {payload.procedure_id}:{payload.version or 'latest'}",
                    "node_id": node.node_id,
                },
                "terminal_status": "failed",
                "next_node_id": None,
                "current_node_id": node.node_id,
            }  # type: ignore

        await run_service.emit_event(
            db,
            run_id,
            "subflow_started",
            node_id=node.node_id,
            payload={"procedure_id": child_proc.procedure_id, "version": child_proc.version},
        )
        await db.commit()

    ckp_dict = json.loads(child_proc.ckp_json) if isinstance(child_proc.ckp_json, str) else child_proc.ckp_json
    child_ir = parse_ckp(ckp_dict)
    validation_errors = validate_ir(child_ir)
    if validation_errors:
        return {
            **state,
            "error": {
                "message": "Subflow validation failed",
                "node_id": node.node_id,
                "errors": validation_errors,
            },
            "terminal_status": "failed",
            "next_node_id": None,
            "current_node_id": node.node_id,
        }  # type: ignore

    bind_executors(child_ir)
    child_graph = build_graph(child_ir, db_factory=db_factory)

    child_initial: OrchestratorState = {
        "vars": child_vars,
        "secrets": state.get("secrets", {}),
        "run_id": run_id,
        "procedure_id": child_ir.procedure_id,
        "procedure_version": child_ir.version,
        "current_node_id": child_ir.start_node_id,
        "current_step_id": None,
        "next_node_id": None,
        "error": None,
        "loop_iterator": None,
        "loop_index": 0,
        "loop_item": None,
        "loop_results": None,
        "approval_id": None,
        "approval_decision": None,
        "telemetry": {},
        "artifacts": [],
        "terminal_status": None,
    }

    subflow_thread_id = f"{run_id}:subflow:{node.node_id}:{child_ir.procedure_id}:{child_ir.version}"
    child_final = await _invoke_with_optional_checkpointer(child_graph, child_initial, subflow_thread_id)

    if child_final.get("error"):
        on_failure = (payload.on_failure or "fail_parent").lower()
        if on_failure == "continue":
            return {
                **state,
                "vars": vs,
                "next_node_id": payload.next_node_id,
                "current_node_id": node.node_id,
            }  # type: ignore
        return {
            **state,
            "error": {
                "message": "Subflow execution failed",
                "node_id": node.node_id,
                "subflow_error": child_final.get("error"),
            },
            "terminal_status": "failed",
            "next_node_id": None,
            "current_node_id": node.node_id,
        }  # type: ignore

    child_out_vars = dict(child_final.get("vars", {}))
    if payload.output_mapping:
        for parent_key, child_value_key in payload.output_mapping.items():
            if isinstance(child_value_key, str):
                vs[parent_key] = child_out_vars.get(child_value_key)
            else:
                vs[parent_key] = child_value_key
    else:
        vs["subflow_output"] = child_out_vars

    async with db_factory() as db:
        await run_service.emit_event(
            db,
            run_id,
            "subflow_completed",
            node_id=node.node_id,
            payload={"procedure_id": child_ir.procedure_id, "version": child_ir.version},
        )
        await db.commit()

    return {
        **state,
        "vars": vs,
        "next_node_id": payload.next_node_id,
        "current_node_id": node.node_id,
    }  # type: ignore


def execute_terminate(node: IRNode, state: OrchestratorState) -> OrchestratorState:
    """Mark run as terminated."""
    payload: IRTerminatePayload = node.payload
    return {
        **state,
        "terminal_status": payload.status,
        "next_node_id": None,
        "current_node_id": node.node_id,
    }  # type: ignore


# ── Internal action dispatcher ──────────────────────────────────


async def _execute_step_action(action: str, params: dict, vars_ctx: dict) -> Any:
    """Async wrapper for internal actions; supports `wait` via asyncio.sleep."""
    if action == "wait":
        duration_ms = int(params.get("duration_ms") or params.get("wait_ms") or 0)
        await asyncio.sleep(max(0, duration_ms) / 1000.0)
        return {"waited_ms": duration_ms}
    return _execute_internal_action(action, params, vars_ctx)


def _execute_internal_action(action: str, params: dict, vars_ctx: dict) -> Any:
    """Handle generic/internal actions (log, set_variable, screenshot, etc.)."""
    if action == "log":
        msg = params.get("message") or params.get("value", "")
        level = params.get("level", "INFO")
        logger.log(getattr(logging, level, logging.INFO), "[CKP] %s", msg)
        return None
    if action == "set_variable":
        var = params.get("variable", "")
        val = params.get("value")
        if var:
            vars_ctx[var] = val
        return val
    if action == "screenshot":
        logger.info("[CKP] screenshot requested")
        return {"screenshot": "placeholder"}
    # Unknown or external action — return params as-is for connector dispatch
    return {"action": action, "params": params}


def _execute_transform_op(
    op_type: str,
    source: Any,
    expression: str,
    params: dict[str, Any],
    vars_ctx: dict[str, Any],
) -> Any:
    op = (op_type or "").lower()

    if op == "filter":
        items = source if isinstance(source, list) else []
        out: list[Any] = []
        for item in items:
            ctx = {**vars_ctx, "item": item}
            expr = render_template_str(expression, ctx)
            if evaluate_condition(expr, ctx):
                out.append(item)
        return out

    if op == "map":
        items = source if isinstance(source, list) else []
        out: list[Any] = []
        for item in items:
            ctx = {**vars_ctx, "item": item}
            if "{{" in expression:
                out.append(render_template_str(expression, ctx))
            elif expression in ("item", "{{item}}"):
                out.append(item)
            elif isinstance(item, dict) and expression in item:
                out.append(item.get(expression))
            else:
                out.append(item)
        return out

    if op == "aggregate":
        items = source if isinstance(source, list) else []
        agg = str(params.get("op") or expression or "count").lower()
        field = params.get("field")
        if agg == "count":
            return len(items)
        if agg == "sum":
            if field:
                return sum((it.get(field, 0) if isinstance(it, dict) else 0) for it in items)
            return sum((it if isinstance(it, (int, float)) else 0) for it in items)
        if agg == "min":
            vals = [(it.get(field) if field and isinstance(it, dict) else it) for it in items]
            vals = [v for v in vals if v is not None]
            return min(vals) if vals else None
        if agg == "max":
            vals = [(it.get(field) if field and isinstance(it, dict) else it) for it in items]
            vals = [v for v in vals if v is not None]
            return max(vals) if vals else None
        return items

    if op == "sort":
        items = source if isinstance(source, list) else []
        key_field = params.get("key") or expression
        reverse = bool(params.get("descending", False))
        if key_field:
            return sorted(
                items,
                key=lambda x: x.get(key_field) if isinstance(x, dict) else x,
                reverse=reverse,
            )
        return sorted(items, reverse=reverse)

    if op == "unique":
        items = source if isinstance(source, list) else []
        seen: set[str] = set()
        out: list[Any] = []
        for item in items:
            key = json.dumps(item, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    return source


async def _execute_branch_path(
    start_node_id: str,
    join_node_id: str | None,
    state: OrchestratorState,
    nodes: dict[str, IRNode],
    db_factory: Callable | None = None,
) -> OrchestratorState:
    current = start_node_id
    current_state: OrchestratorState = dict(state)
    max_hops = 1000
    hops = 0

    while current and (join_node_id is None or current != join_node_id):
        hops += 1
        if hops > max_hops:
            return {
                **current_state,
                "error": {"message": "Parallel branch exceeded max hops", "node_id": current},
                "terminal_status": "failed",
                "next_node_id": None,
            }  # type: ignore

        branch_node = nodes.get(current)
        if not branch_node:
            return {
                **current_state,
                "error": {
                    "message": f"Parallel branch node '{current}' not found",
                    "node_id": current,
                },
                "terminal_status": "failed",
                "next_node_id": None,
            }  # type: ignore

        current_state["current_node_id"] = current
        current_state["next_node_id"] = None
        current_state = await _execute_node(branch_node, current_state, nodes=nodes, db_factory=db_factory)

        if current_state.get("error") or current_state.get("terminal_status") in {"failed", "awaiting_approval"}:
            return current_state

        next_node = current_state.get("next_node_id")
        if not next_node:
            next_node = branch_node.next_node_id or getattr(branch_node.payload, "next_node_id", None)

        if not next_node:
            break

        current = next_node

    return current_state


async def _execute_node(
    node: IRNode,
    state: OrchestratorState,
    nodes: dict[str, IRNode],
    db_factory: Callable | None = None,
) -> OrchestratorState:
    if node.type == "sequence":
        return await execute_sequence(node, state, db_factory=db_factory)
    if node.type == "parallel":
        return await execute_parallel(node, state, db_factory=db_factory, nodes=nodes)
    if node.type == "logic":
        return execute_logic(node, state)
    if node.type == "loop":
        return execute_loop(node, state)
    if node.type == "verification":
        return execute_verification(node, state)
    if node.type == "processing":
        return execute_processing(node, state)
    if node.type == "transform":
        return execute_transform(node, state)
    if node.type == "human_approval":
        return execute_human_approval(node, state)
    if node.type == "llm_action":
        return execute_llm_action(node, state)
    if node.type == "terminate":
        return execute_terminate(node, state)
    return {
        **state,
        "error": {"message": f"Unsupported node type '{node.type}'", "node_id": node.node_id},
        "terminal_status": "failed",
        "next_node_id": None,
        "current_node_id": node.node_id,
    }  # type: ignore


def _compute_var_delta(base_vars: dict[str, Any], branch_vars: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for key, value in branch_vars.items():
        if key not in base_vars or base_vars.get(key) != value:
            delta[key] = value
    return delta


def _extract_artifacts_from_result(result: Any) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []

    if isinstance(result, dict):
        screenshot_value = result.get("screenshot")
        if isinstance(screenshot_value, str) and screenshot_value:
            screenshot_uri = (
                screenshot_value
                if "://" in screenshot_value
                else f"memory://{screenshot_value}"
            )
            artifacts.append({"kind": "screenshot", "uri": screenshot_uri})

        single = result.get("artifact")
        if isinstance(single, dict):
            artifacts.append(single)

        many = result.get("artifacts")
        if isinstance(many, list):
            artifacts.extend([item for item in many if isinstance(item, dict)])

        uri = result.get("artifact_uri") or result.get("uri")
        if isinstance(uri, str) and uri:
            artifacts.append({"kind": result.get("artifact_kind", "artifact"), "uri": uri})

    return artifacts


async def _get_completed_step_result(db, run_id: str, node_id: str, step_id: str) -> Any | None:
    from app.db.models import StepIdempotency

    record = await db.get(StepIdempotency, (run_id, node_id, step_id))
    if not record or record.status != "completed":
        return None
    if not record.result_json:
        return None
    try:
        return json.loads(record.result_json)
    except Exception:
        return record.result_json


async def _mark_step_started(
    db,
    run_id: str,
    node_id: str,
    step_id: str,
    idempotency_key: str | None,
) -> None:
    from app.db.models import StepIdempotency

    record = await db.get(StepIdempotency, (run_id, node_id, step_id))
    if record is None:
        db.add(
            StepIdempotency(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                idempotency_key=idempotency_key,
                status="started",
            )
        )
        return

    record.status = "started"
    if idempotency_key:
        record.idempotency_key = idempotency_key


async def _mark_step_completed(db, run_id: str, node_id: str, step_id: str, result: Any) -> None:
    from app.db.models import StepIdempotency

    serialized = json.dumps(result, default=str) if result is not None else None
    record = await db.get(StepIdempotency, (run_id, node_id, step_id))
    if record is None:
        db.add(
            StepIdempotency(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                status="completed",
                result_json=serialized,
            )
        )
        return

    record.status = "completed"
    record.result_json = serialized


async def _mark_step_failed(db, run_id: str, node_id: str, step_id: str) -> None:
    from app.db.models import StepIdempotency

    record = await db.get(StepIdempotency, (run_id, node_id, step_id))
    if record is None:
        db.add(
            StepIdempotency(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                status="failed",
            )
        )
        return

    record.status = "failed"


async def _acquire_agent_lease(
    db,
    agent_url: str,
    run_id: str,
    node_id: str,
    step_id: str,
) -> str | None:
    from sqlalchemy import select

    from app.db.models import AgentInstance
    from app.services import lease_service

    stmt = (
        select(AgentInstance)
        .where(AgentInstance.base_url == agent_url)
        .where(AgentInstance.status == "online")
        .limit(1)
    )
    result = await db.execute(stmt)
    instance = result.scalars().first()
    if not instance or not instance.resource_key:
        return None

    lease = await lease_service.try_acquire_lease(
        db,
        resource_key=instance.resource_key,
        run_id=run_id,
        node_id=node_id,
        step_id=step_id,
    )
    if not lease:
        raise RuntimeError(f"Resource busy for agent '{instance.agent_id}' ({instance.resource_key})")

    return lease.lease_id


async def _release_lease(db, lease_id: str) -> None:
    from app.services import lease_service

    await lease_service.release_lease(db, lease_id)


async def _invoke_with_optional_checkpointer(graph, initial_state: OrchestratorState, thread_id: str):
    runnable_config = {"configurable": {"thread_id": thread_id}}
    checkpointer_url = settings.CHECKPOINTER_URL

    if checkpointer_url:
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            async with AsyncSqliteSaver.from_conn_string(checkpointer_url) as checkpointer:
                compiled = graph.compile(checkpointer=checkpointer)
                return await compiled.ainvoke(initial_state, config=runnable_config)
        except Exception:
            logger.exception("Failed to initialize subflow checkpointer; running without checkpoint")

    compiled = graph.compile()
    return await compiled.ainvoke(initial_state, config=runnable_config)
