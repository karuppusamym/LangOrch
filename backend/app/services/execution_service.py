"""Run execution engine — compiles CKP, builds graph, and executes."""

from __future__ import annotations

import json
import logging
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

            # Phase 2: Build graph — pass db_factory so sequence nodes can
            # resolve executors dynamically from the agent registry at runtime.
            graph = build_graph(ir, db_factory=db_factory, entry_node_id=resume_entry_node)
            

            # Phase 3: Execute
            initial_state: OrchestratorState = {
                "vars": {**ir.variables_schema, **input_vars},
                "secrets": {},
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

            if error:
                await run_service.update_run_status(db, run_id, "failed")
                await run_service.emit_event(
                    db, run_id, "run_failed", payload={"error": error}
                )
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
            else:
                await run_service.update_run_status(db, run_id, "completed")
                await run_service.emit_event(
                    db, run_id, "run_completed",
                    payload={"outputs": final_state.get("vars", {})}
                )

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
