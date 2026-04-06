"""Checkpoint introspection service for LangGraph checkpoints."""

from __future__ import annotations

from typing import Any
import json

from app.config import settings


async def list_checkpoints(thread_id: str) -> list[dict[str, Any]]:
    """
    List all checkpoints for a given thread (run).
    
    Args:
        thread_id: The thread ID (typically run_id or custom thread_id)
        
    Returns:
        List of checkpoint metadata dictionaries
    """
    checkpointer_url = settings.CHECKPOINTER_URL
    if not checkpointer_url:
        return []
    
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        
        async with AsyncSqliteSaver.from_conn_string(checkpointer_url) as checkpointer:
            # LangGraph checkpointer API: list checkpoints for a thread
            checkpoints = []
            config = {"configurable": {"thread_id": thread_id}}

            async for checkpoint_tuple in checkpointer.alist(config):
                checkpoint_config = checkpoint_tuple.config
                checkpoint_metadata = checkpoint_tuple.metadata
                checkpoint_id = checkpoint_config.get("configurable", {}).get("checkpoint_id")

                # Resolve parent checkpoint ID from parent_config (more reliable than metadata)
                _parent_config = getattr(checkpoint_tuple, "parent_config", None)
                _parent_ckpt_id = (
                    _parent_config.get("configurable", {}).get("checkpoint_id")
                    if isinstance(_parent_config, dict)
                    else None
                )

                # LangGraph stores the checkpoint timestamp in checkpoint["ts"] as an ISO string.
                # metadata["source"] is a string like "loop"/"update", NOT a date.
                _checkpoint_data = getattr(checkpoint_tuple, "checkpoint", None) or {}
                _ts = (
                    _checkpoint_data.get("ts")
                    if isinstance(_checkpoint_data, dict)
                    else None
                )

                checkpoints.append({
                    "checkpoint_id": checkpoint_id,
                    "thread_id": thread_id,
                    "parent_checkpoint_id": _parent_ckpt_id,
                    "step": checkpoint_metadata.get("step", 0),
                    "writes": checkpoint_metadata.get("writes"),
                    "created_at": _ts or "",
                })

            return checkpoints
            
    except Exception as e:
        # Log error but don't fail - checkpointing is optional
        import logging
        logger = logging.getLogger("langorch.checkpoint")
        logger.warning("Failed to list checkpoints for thread %s: %s", thread_id, e)
        return []


async def get_checkpoint_state(thread_id: str, checkpoint_id: str | None = None) -> dict[str, Any] | None:
    """
    Get the state at a specific checkpoint.
    
    Args:
        thread_id: The thread ID (typically run_id)
        checkpoint_id: Optional checkpoint ID (if None, gets latest)
        
    Returns:
        Checkpoint state dictionary or None if not found
    """
    checkpointer_url = settings.CHECKPOINTER_URL
    if not checkpointer_url:
        return None
    
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        
        async with AsyncSqliteSaver.from_conn_string(checkpointer_url) as checkpointer:
            config = {"configurable": {"thread_id": thread_id}}
            if checkpoint_id:
                config["configurable"]["checkpoint_id"] = checkpoint_id
            
            # Get checkpoint
            checkpoint_tuple = await checkpointer.aget(config)
            if not checkpoint_tuple:
                return None
            
            checkpoint = checkpoint_tuple.checkpoint
            checkpoint_config = checkpoint_tuple.config
            checkpoint_metadata = checkpoint_tuple.metadata
            
            return {
                "checkpoint_id": checkpoint_config.get("configurable", {}).get("checkpoint_id"),
                "thread_id": thread_id,
                "channel_values": checkpoint.get("channel_values", {}),
                "metadata": checkpoint_metadata,
                "pending_writes": checkpoint.get("pending_writes", []),
                "versions_seen": checkpoint.get("versions_seen", {}),
            }
            
    except Exception as e:
        import logging
        logger = logging.getLogger("langorch.checkpoint")
        logger.warning("Failed to get checkpoint state for thread %s: %s", thread_id, e)
        return None
