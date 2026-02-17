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
            
            # Get checkpoint history using the checkpointer's list method
            async for checkpoint_tuple in checkpointer.list(config):
                checkpoint_config = checkpoint_tuple.config
                checkpoint_metadata = checkpoint_tuple.metadata
                checkpoint_id = checkpoint_config.get("configurable", {}).get("checkpoint_id")
                
                checkpoints.append({
                    "checkpoint_id": checkpoint_id,
                    "thread_id": thread_id,
                    "parent_checkpoint_id": checkpoint_metadata.get("parent_checkpoint_id"),
                    "step": checkpoint_metadata.get("step", 0),
                    "writes": checkpoint_metadata.get("writes"),
                    "created_at": checkpoint_metadata.get("source", "unknown"),
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
