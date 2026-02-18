"""LangGraph state schema for orchestrator runs."""

from __future__ import annotations

from typing import Any, TypedDict


class OrchestratorState(TypedDict, total=False):
    """Single state object carried through the LangGraph execution."""

    # Workflow variables (required + optional + step outputs)
    vars: dict[str, Any]

    # Secrets — resolved at runtime, NEVER persisted in checkpoints
    secrets: dict[str, Any]

    # Run context
    run_id: str
    procedure_id: str
    procedure_version: str
    global_config: dict  # global_config from CKP IR — retry, rate_limit, sla, etc.
    execution_mode: str  # "production" (default) | "dry_run" | "validation_only"

    # Cursor — tracks where we are
    current_node_id: str
    current_step_id: str | None

    # Routing key — set by each node to tell conditional edges where to go
    next_node_id: str | None

    # Error context
    error: dict[str, Any] | None

    # Loop context
    loop_iterator: list[Any] | None
    loop_index: int
    loop_item: Any
    loop_results: list[Any] | None

    # HITL
    approval_id: str | None
    approval_decision: str | None
    awaiting_approval: dict[str, Any] | None

    # Telemetry
    telemetry: dict[str, Any]

    # Artifacts collected during run
    artifacts: list[dict[str, Any]]

    # Terminal status
    terminal_status: str | None

    # Selective checkpointing — set by graph_builder when node.is_checkpoint=True
    # execution_service reads this to force-save a checkpoint snapshot after the node
    _checkpoint_node_id: str | None
