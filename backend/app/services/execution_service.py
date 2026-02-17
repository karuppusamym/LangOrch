"""Run execution engine — compiles CKP, builds graph, and executes."""

from __future__ import annotations

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

logger = logging.getLogger("langorch.execution")


async def _invoke_graph_with_checkpointer(graph, initial_state: OrchestratorState, thread_id: str):
    runnable_config = {"configurable": {"thread_id": thread_id}}
    checkpointer_url = settings.CHECKPOINTER_URL

    if checkpointer_url:
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            async with AsyncSqliteSaver.from_conn_string(checkpointer_url) as checkpointer:
                compiled = graph.compile(checkpointer=checkpointer)
                return await compiled.ainvoke(initial_state, config=runnable_config)
        except Exception as exc:
            logger.warning(
                "Failed to initialize SQLite checkpointer (%s). Falling back to non-checkpointed run.",
                exc,
            )

    compiled = graph.compile()
    return await compiled.ainvoke(initial_state, config=runnable_config)


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
            

            # Phase 4: Execute
            initial_state: OrchestratorState = {
                "vars": {**ir.variables_schema, **input_vars},
                "secrets": secrets_dict,
                "run_id": run_id,
                "procedure_id": ir.procedure_id,
                "procedure_version": ir.version,
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
            final_state = await _invoke_graph_with_checkpointer(graph, initial_state, thread_id)

            # Determine outcome
            terminal = final_state.get("terminal_status", "success")
            error = final_state.get("error")
            awaiting_approval = final_state.get("awaiting_approval")
            
            # Calculate run duration
            run_duration = (datetime.now(timezone.utc) - run_start_time).total_seconds()

            if error:
                await run_service.update_run_status(db, run_id, "failed")
                await run_service.emit_event(
                    db, run_id, "run_failed", payload={"error": error}
                )
                record_run_completed(run_duration, "failed")
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
                await run_service.update_run_status(db, run_id, "failed")
                await run_service.emit_event(db, run_id, "run_failed")
                record_run_completed(run_duration, "failed")
            else:
                await run_service.update_run_status(db, run_id, "completed")
                await run_service.emit_event(
                    db, run_id, "run_completed",
                    payload={"outputs": final_state.get("vars", {})}
                )
                record_run_completed(run_duration, "completed")

            await db.commit()
            logger.info("Run %s finished with status: %s", run_id, terminal)

        except Exception as exc:
            logger.exception("Run %s failed with exception", run_id)
            try:
                await run_service.update_run_status(db, run_id, "failed")
                await run_service.emit_event(
                    db, run_id, "error",
                    payload={"message": str(exc), "type": type(exc).__name__}
                )
                await db.commit()
            except Exception:
                logger.exception("Failed to update run status after error")
