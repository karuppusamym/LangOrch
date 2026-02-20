"""Run execution engine — compiles CKP, builds graph, and executes."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compiler.parser import parse_ckp
from app.compiler.validator import validate_ir
from app.compiler.binder import bind_executors
from app.config import settings
from app.runtime.graph_builder import build_graph
from app.runtime.state import OrchestratorState
from app.db.models import RunEvent
from app.services import approval_service, run_service
from app.services.secrets_service import get_secrets_manager, configure_secrets_provider, EnvironmentSecretsProvider, VaultSecretsProvider
from app.utils.metrics import record_run_started, record_run_completed
from app.utils.run_cancel import RunCancelledError, register as _cancel_register, deregister as _cancel_deregister

logger = logging.getLogger("langorch.execution")


async def _fire_alert_webhook(run_id: str, error: Any) -> None:
    """POST a run_failed alert to ALERT_WEBHOOK_URL if configured."""
    url = settings.ALERT_WEBHOOK_URL
    if not url:
        return
    try:
        import httpx
        payload = {
            "event": "run_failed",
            "run_id": run_id,
            "error": str(error) if error else None,
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                logger.warning("Alert webhook returned %s for run %s", resp.status_code, run_id)
    except Exception as exc:
        logger.warning("Failed to fire alert webhook for run %s: %s", run_id, exc)


async def _run_on_failure_handler(
    ir: Any,
    current_state: dict,
    run_id: str,
    error_msg: str,
    db_factory,
    thread_id: str,
) -> dict | None:
    """Invoke the global on_failure node as a recovery handler.

    Returns the final state of the recovery graph, or None if:
    - No on_failure node is configured.
    - The node ID does not exist in the IR.
    - The handler itself raises an exception.
    """
    on_failure_node = ir.global_config.get("on_failure")
    if not on_failure_node or on_failure_node not in ir.nodes:
        return None
    logger.info(
        "Run %s: invoking on_failure node '%s' after error: %s",
        run_id, on_failure_node, error_msg,
    )
    try:
        recovery_state = {
            **current_state,
            "next_node_id": None,
            "current_node_id": on_failure_node,
            "error": {"message": error_msg},
            "terminal_status": None,
        }
        recovery_graph = build_graph(ir, db_factory=db_factory, entry_node_id=on_failure_node)
        return await _invoke_graph_with_checkpointer(
            recovery_graph, recovery_state, f"{thread_id}:on_failure"
        )
    except Exception as fb_exc:
        logger.warning("on_failure handler for run %s also failed: %s", run_id, fb_exc)
        return None


def _validate_var_constraints(
    variables_schema: dict,
    input_vars: dict,
) -> list[str]:
    """Validate provided input_vars against schema constraints (regex/max/allowed_values).
    Returns a list of human-readable error strings (empty = all OK)."""
    import re as _re

    errors: list[str] = []
    for var_name, meta in variables_schema.items():
        if not isinstance(meta, dict):
            continue
        value = input_vars.get(var_name)
        if value is None:
            continue  # Required check is done separately
        validation = meta.get("validation") or {}
        vtype = meta.get("type", "string")

        # regex — string only
        pattern = validation.get("regex")
        if pattern and isinstance(value, str):
            if not _re.fullmatch(pattern, value):
                errors.append(
                    f"Variable '{var_name}': value {value!r} does not match pattern '{pattern}'"
                )

        # max — numeric
        max_val = validation.get("max")
        if max_val is not None and isinstance(value, (int, float)):
            if value > max_val:
                errors.append(
                    f"Variable '{var_name}': value {value} exceeds maximum {max_val}"
                )

        # min — numeric
        min_val = validation.get("min")
        if min_val is not None and isinstance(value, (int, float)):
            if value < min_val:
                errors.append(
                    f"Variable '{var_name}': value {value} is below minimum {min_val}"
                )

        # allowed_values
        allowed = validation.get("allowed_values")
        if allowed is not None:
            if value not in allowed:
                errors.append(
                    f"Variable '{var_name}': value {value!r} not in allowed values {allowed}"
                )

    return errors


async def _invoke_graph_with_checkpointer(
    graph,
    initial_state: OrchestratorState,
    thread_id: str,
    timeout_ms: int | None = None,
    db_factory=None,
    run_id: str | None = None,
):
    runnable_config = {"configurable": {"thread_id": thread_id}}
    checkpointer_url = settings.CHECKPOINTER_URL

    async def _invoke(compiled) -> OrchestratorState:
        """Stream graph events and detect selective checkpoint markers."""
        final: OrchestratorState = {}
        try:
            stream_coro = compiled.astream(
                initial_state,
                config=runnable_config,
                stream_mode="updates",
            )
            if timeout_ms and timeout_ms > 0:
                # Wrap the whole stream iteration inside a timeout
                async def _consume():
                    nonlocal final
                    async for chunk in stream_coro:
                        # chunk is {node_name: state_patch}
                        for _node_name, state_patch in chunk.items():
                            if isinstance(state_patch, dict):
                                final = {**final, **state_patch}
                                # Detect is_checkpoint marker
                                ckp_nid = state_patch.get("_checkpoint_node_id")
                                if ckp_nid and db_factory and run_id:
                                    await _emit_checkpoint_event(db_factory, run_id, ckp_nid)
                    return final

                try:
                    return await asyncio.wait_for(_consume(), timeout=timeout_ms / 1000.0)
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"Procedure execution timed out after {timeout_ms}ms "
                        f"(global_config.timeout_ms)"
                    )
            else:
                async for chunk in stream_coro:
                    for _node_name, state_patch in chunk.items():
                        if isinstance(state_patch, dict):
                            final = {**final, **state_patch}
                            ckp_nid = state_patch.get("_checkpoint_node_id")
                            if ckp_nid and db_factory and run_id:
                                await _emit_checkpoint_event(db_factory, run_id, ckp_nid)
                return final
        except asyncio.TimeoutError:
            raise

    if checkpointer_url:
        # Honor checkpoint_strategy: "none" → skip checkpointing even if URL is set
        checkpoint_strategy = getattr(graph, "_ckp_strategy", None) or "full"
        if checkpoint_strategy == "none":
            compiled = graph.compile()
            return await _invoke(compiled)
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            async with AsyncSqliteSaver.from_conn_string(checkpointer_url) as checkpointer:
                compiled = graph.compile(checkpointer=checkpointer)
                return await _invoke(compiled)
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to initialize SQLite checkpointer (%s). Falling back to non-checkpointed run.",
                exc,
            )

    compiled = graph.compile()
    return await _invoke(compiled)


async def _emit_checkpoint_event(db_factory, run_id: str, node_id: str) -> None:
    """Emit a checkpoint_saved DB event for a selective is_checkpoint node."""
    try:
        async with db_factory() as db:
            await run_service.emit_event(
                db,
                run_id,
                "checkpoint_saved",
                node_id=node_id,
                payload={"reason": "is_checkpoint", "node_id": node_id},
            )
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to emit checkpoint_saved event for run %s node %s: %s", run_id, node_id, exc)


async def execute_run(run_id: str, db_factory) -> None:
    """
    Full run execution pipeline (called as a background task):
      1. Load the procedure's CKP JSON
      2. Compile CKP → IR
      3. Validate IR
      4. Bind executors
      5. Build LangGraph StateGraph
      6. Execute with initial state
      7. Update run status + emit events
    """
    async with db_factory() as db:
        _cancel_register(run_id)
        try:
            # Load run
            run = await run_service.get_run(db, run_id)
            if not run:
                logger.error("Run %s not found", run_id)
                return

            # Parse input vars once so we can detect resume intent before execution
            input_vars = json.loads(run.input_vars_json) if run.input_vars_json else {}
            approval_decisions = input_vars.get("__approval_decisions", {})
            if not isinstance(approval_decisions, dict):
                approval_decisions = {}

            retry_requested = False
            if run.last_node_id:
                retry_stmt = (
                    select(RunEvent.event_id)
                    .where(RunEvent.run_id == run_id)
                    .where(RunEvent.event_type == "run_retry_requested")
                    .limit(1)
                )
                retry_requested = (await db.execute(retry_stmt)).first() is not None

            resume_entry_node = None
            resume_reason = None
            if run.last_node_id and approval_decisions.get(run.last_node_id):
                resume_entry_node = run.last_node_id
                resume_reason = "approval_resume"
            elif run.last_node_id and retry_requested:
                resume_entry_node = run.last_node_id
                resume_reason = "retry_fallback"

            # Mark running
            await run_service.update_run_status(db, run_id, "running")
            await db.commit()
            
            # Record metrics
            run_start_time = datetime.now(timezone.utc)
            record_run_started()

            # Load procedure
            from app.services import procedure_service
            proc = await procedure_service.get_procedure(
                db, run.procedure_id, run.procedure_version
            )
            if not proc:
                await run_service.update_run_status(db, run_id, "failed")
                await run_service.emit_event(
                    db, run_id, "error", payload={"message": "Procedure not found"}
                )
                await db.commit()
                return

            ckp_dict = json.loads(proc.ckp_json) if isinstance(proc.ckp_json, str) else proc.ckp_json

            # Enforce procedure status — block deprecated/archived procedures
            _blocked_statuses = ("deprecated", "archived")
            if proc.status in _blocked_statuses:
                await run_service.update_run_status(db, run_id, "failed")
                await run_service.emit_event(
                    db, run_id, "error",
                    payload={"message": f"Procedure is {proc.status} and cannot be executed"},
                )
                await db.commit()
                return

            # Enforce effective_date — procedure should not run before its effective date
            if proc.effective_date:
                from datetime import date
                try:
                    eff = date.fromisoformat(proc.effective_date)
                    if date.today() < eff:
                        await run_service.update_run_status(db, run_id, "failed")
                        await run_service.emit_event(
                            db, run_id, "error",
                            payload={"message": f"Procedure is not yet effective until {proc.effective_date}"},
                        )
                        await db.commit()
                        return
                except (ValueError, TypeError):
                    pass  # malformed date — ignore

            # Phase 1: Compile
            ir = parse_ckp(ckp_dict)
            errors = validate_ir(ir)
            if errors:
                await run_service.update_run_status(db, run_id, "failed")
                await run_service.emit_event(
                    db, run_id, "error",
                    payload={"message": "CKP validation failed", "errors": errors}
                )
                await db.commit()
                return

            bind_executors(ir)

            # Validate required input variables are present before execution
            missing_required = [
                k for k, v in ir.variables_schema.items()
                if isinstance(v, dict) and v.get("required") and k not in input_vars
            ]
            if missing_required:
                await run_service.update_run_status(db, run_id, "failed")
                await run_service.emit_event(
                    db, run_id, "error",
                    payload={
                        "message": f"Missing required input variable(s): {', '.join(missing_required)}",
                        "missing_vars": missing_required,
                    },
                )
                await db.commit()
                return

            # Validate schema constraints (regex, min, max, allowed_values)
            constraint_errors = _validate_var_constraints(ir.variables_schema, input_vars)
            if constraint_errors:
                await run_service.update_run_status(db, run_id, "failed")
                await run_service.emit_event(
                    db, run_id, "error",
                    payload={
                        "message": "Input variable constraint violation(s)",
                        "errors": constraint_errors,
                    },
                )
                await db.commit()
                return

            # Check execution_mode — skip real execution for dry_run / validation_only
            execution_mode = ir.global_config.get("execution_mode", "production")
            if execution_mode in ("dry_run", "validation_only"):
                logger.info(
                    "Run %s: execution_mode=%s — skipping graph execution",
                    run_id, execution_mode,
                )
                await run_service.update_run_status(db, run_id, "completed")
                await run_service.emit_event(
                    db, run_id, "run_completed",
                    payload={
                        "mode": execution_mode,
                        "message": f"Execution skipped (mode={execution_mode}). CKP compiled and validated successfully.",
                        "outputs": {},
                    },
                )
                record_run_completed((datetime.now(timezone.utc) - run_start_time).total_seconds(), "completed")
                await db.commit()
                return

            # Phase 2: Load secrets from configured provider
            secrets_dict = {}
            secrets_config = ir.global_config.get("secrets_config", {})
            provider_type = secrets_config.get("provider", "env_vars")
            
            try:
                # Configure secrets provider based on CKP config
                if provider_type == "hashicorp_vault":
                    vault_url = secrets_config.get("vault_url")
                    if vault_url:
                        provider = VaultSecretsProvider(vault_url=vault_url)
                        configure_secrets_provider(provider)
                        logger.info("Configured Vault secrets provider: %s", vault_url)
                elif provider_type in ["azure_keyvault", "aws_secrets"]:
                    logger.warning("Secrets provider '%s' not yet implemented, falling back to env_vars", provider_type)
                    # Fallback to environment variables
                    configure_secrets_provider(EnvironmentSecretsProvider())
                else:
                    # Default to environment variables
                    configure_secrets_provider(EnvironmentSecretsProvider())
                
                # Load secrets referenced in CKP
                secret_references = secrets_config.get("secret_references", {})
                if secret_references:
                    secrets_manager = get_secrets_manager()
                    for secret_key, secret_ref in secret_references.items():
                        # secret_ref could be a string (key name) or dict with metadata
                        lookup_key = secret_ref if isinstance(secret_ref, str) else secret_ref.get("key", secret_key)
                        secret_value = await secrets_manager.get_secret(lookup_key)
                        if secret_value:
                            secrets_dict[secret_key] = secret_value
                            logger.info("Loaded secret: %s", secret_key)
                        else:
                            logger.warning("Secret not found: %s", secret_key)
            
            except Exception as exc:
                logger.warning("Failed to load secrets: %s", exc)
                # Continue execution with empty secrets - let workflow handle missing secrets

            # Phase 3: Build graph — pass db_factory so sequence nodes can
            # resolve executors dynamically from the agent registry at runtime.
            graph = build_graph(ir, db_factory=db_factory, entry_node_id=resume_entry_node)
            # Tag graph with checkpoint_strategy so _invoke_graph_with_checkpointer can honor it
            _ckp_strategy = ir.global_config.get("checkpoint_strategy", "full")
            graph._ckp_strategy = _ckp_strategy  # type: ignore[attr-defined]

            # Phase 4: Execute
            # Build vars: extract schema defaults, then overlay with actual input_vars.
            # ir.variables_schema is a dict of meta-dicts like {"type": ..., "default": ...};
            # spreading it directly would pollute the vars namespace with schema objects.
            schema_defaults = {
                k: v.get("default")
                for k, v in ir.variables_schema.items()
                if isinstance(v, dict) and "default" in v
            }

            # Rate limiting: build asyncio.Semaphore if global_config.rate_limiting.max_concurrent is set
            _rl_cfg = ir.global_config.get("rate_limiting") or {}
            _max_concurrent = int(_rl_cfg.get("max_concurrent") or settings.RATE_LIMIT_MAX_CONCURRENT or 0)
            _rate_semaphore = asyncio.Semaphore(_max_concurrent) if _max_concurrent > 0 else None

            # Inject rate semaphore into global_config dict so node_executors can retrieve it from state
            _gc_for_state = dict(ir.global_config)
            if _rate_semaphore is not None:
                _gc_for_state["_rate_semaphore"] = _rate_semaphore

            initial_state: OrchestratorState = {
                "vars": {**schema_defaults, **input_vars},
                "secrets": secrets_dict,
                "run_id": run_id,
                "procedure_id": ir.procedure_id,
                "procedure_version": ir.version,
                "global_config": _gc_for_state,
                "execution_mode": execution_mode,
                "current_node_id": resume_entry_node or ir.start_node_id,
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

            await run_service.emit_event(
                db,
                run_id,
                "execution_started",
                payload={
                    "entry_node_id": resume_entry_node or ir.start_node_id,
                    "resume_reason": resume_reason,
                },
            )
            await db.commit()

            # Run the graph (async invoke — supports async node executors)
            thread_id = run.thread_id or run_id
            global_timeout_ms: int | None = (
                int(ir.global_config["timeout_ms"])
                if ir.global_config.get("timeout_ms")
                else None
            )
            final_state = await _invoke_graph_with_checkpointer(
                graph, initial_state, thread_id, timeout_ms=global_timeout_ms,
                db_factory=db_factory, run_id=run_id,
            )

            # Determine outcome
            terminal = final_state.get("terminal_status", "success")
            error = final_state.get("error")
            awaiting_approval = final_state.get("awaiting_approval")
            
            # Calculate run duration
            run_duration = (datetime.now(timezone.utc) - run_start_time).total_seconds()

            if error:
                on_failure_node = ir.global_config.get("on_failure")
                if on_failure_node and on_failure_node in ir.nodes:
                    fb_state = await _run_on_failure_handler(
                        ir, final_state, run_id, str(error), db_factory, thread_id
                    )
                    if fb_state and not fb_state.get("error") and fb_state.get("terminal_status") != "failed":
                        await run_service.update_run_status(db, run_id, "completed")
                        await run_service.emit_event(
                            db, run_id, "run_completed",
                            payload={"outputs": fb_state.get("vars", {}), "recovered_via": on_failure_node},
                        )
                        record_run_completed(run_duration, "completed")
                        await db.commit()
                        return
                error_msg = str(error.get("message", error) if isinstance(error, dict) else error)
                await run_service.update_run_status(db, run_id, "failed", error_message=error_msg)
                await run_service.emit_event(
                    db, run_id, "run_failed", payload={"error": error}
                )
                record_run_completed(run_duration, "failed")
                asyncio.ensure_future(_fire_alert_webhook(run_id, error))
            elif terminal == "awaiting_approval" and isinstance(awaiting_approval, dict):
                # Persist current vars so resume can continue without replaying side effects.
                run.input_vars_json = json.dumps(final_state.get("vars", {}))

                approval = await approval_service.create_approval(
                    db,
                    run_id=run_id,
                    node_id=awaiting_approval.get("node_id", final_state.get("current_node_id", "")),
                    prompt=awaiting_approval.get("prompt", "Approval required"),
                    decision_type=awaiting_approval.get("decision_type", "approve_reject"),
                    options=awaiting_approval.get("options"),
                    context_data=awaiting_approval.get("context_data"),
                    timeout_ms=awaiting_approval.get("timeout_ms"),
                )
                await run_service.update_run_status(
                    db,
                    run_id,
                    "waiting_approval",
                    last_node_id=final_state.get("current_node_id"),
                )
                await run_service.emit_event(
                    db,
                    run_id,
                    "approval_requested",
                    node_id=final_state.get("current_node_id"),
                    payload={"approval_id": approval.approval_id},
                )
            elif terminal == "failed":
                await run_service.update_run_status(db, run_id, "failed", error_message="Execution terminated with failed status")
                await run_service.emit_event(db, run_id, "run_failed")
                record_run_completed(run_duration, "failed")
                asyncio.ensure_future(_fire_alert_webhook(run_id, None))
            else:
                # Persist final output vars alongside the run record
                _final_vars = final_state.get("vars", {})
                run.output_vars_json = json.dumps(_final_vars)
                await run_service.update_run_status(db, run_id, "completed")
                await run_service.emit_event(
                    db, run_id, "run_completed",
                    payload={"outputs": _final_vars}
                )
                record_run_completed(run_duration, "completed")

            await db.commit()
            logger.info("Run %s finished with status: %s", run_id, terminal)

        except RunCancelledError:
            logger.info("Run %s cancelled during execution", run_id)
            try:
                await run_service.update_run_status(db, run_id, "canceled")
                await run_service.emit_event(db, run_id, "run_canceled", payload={"reason": "cancel_signal"})
                await db.commit()
            except Exception:
                logger.exception("Failed to persist cancel status for run %s", run_id)

        except Exception as exc:
            logger.exception("Run %s failed with exception", run_id)
            # Attempt on_failure recovery before marking the run as failed
            _ir = locals().get("ir")
            _thread_id = locals().get("thread_id") or run_id
            _initial = locals().get("initial_state") or {}
            if _ir is not None:
                _on_failure = _ir.global_config.get("on_failure")
                if _on_failure and _on_failure in _ir.nodes:
                    fb = await _run_on_failure_handler(
                        _ir, _initial, run_id, str(exc), db_factory, _thread_id
                    )
                    if fb and not fb.get("error") and fb.get("terminal_status") != "failed":
                        try:
                            _dur = (datetime.now(timezone.utc) - locals().get("run_start_time", datetime.now(timezone.utc))).total_seconds()
                            await run_service.update_run_status(db, run_id, "completed")
                            await run_service.emit_event(
                                db, run_id, "run_completed",
                                payload={"outputs": fb.get("vars", {}), "recovered_via": _on_failure},
                            )
                            record_run_completed(_dur, "completed")
                            await db.commit()
                        except Exception:
                            logger.exception("Failed to persist on_failure recovery status")
                        return
            try:
                await run_service.update_run_status(db, run_id, "failed", error_message=str(exc)[:2000])
                await run_service.emit_event(
                    db, run_id, "error",
                    payload={"message": str(exc), "type": type(exc).__name__}
                )
                await db.commit()
            except Exception:
                logger.exception("Failed to update run status after error")
        finally:
            _cancel_deregister(run_id)
