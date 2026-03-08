"""Agent pool autoscaling policy based on saturation signals and queue depth."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RunEvent

logger = logging.getLogger("langorch.autoscaler")


# Default scaling policy configuration
DEFAULT_POLICY = {
    "enabled": True,
    "saturation_threshold": 3,  # Number of saturation events in window to trigger scale-up
    "saturation_window_minutes": 5,
    "queue_depth_threshold": 10,  # Queue depth to trigger scale-up
    "scale_up_increment": 1,  # Number of instances to request when scaling up
    "scale_down_after_minutes": 15,  # Cooldown before scale-down
    "min_instances": 1,
    "max_instances": 10,
    "hysteresis_factor": 0.8,  # Scale down at 80% of scale-up threshold
}


async def check_pool_saturation_events(
    db: AsyncSession,
    pool_id: str,
    window_minutes: int = 5,
) -> int:
    """Count pool_saturated events for a pool in the recent time window.
    
    Args:
        db: Database session
        pool_id: The agent pool ID to check
        window_minutes: Time window in minutes to check
    
    Returns:
        Number of saturation events in the window
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    
    stmt = (
        select(RunEvent)
        .where(
            RunEvent.event_type == "pool_saturated",
            RunEvent.ts >= cutoff,
        )
    )
    events = (await db.execute(stmt)).scalars().all()
    
    # Filter by pool_id in payload
    pool_events = []
    for event in events:
        try:
            payload = json.loads(event.payload_json) if event.payload_json else {}
            if payload.get("pool_id") == pool_id:
                pool_events.append(event)
        except Exception:
            continue
    
    return len(pool_events)


async def get_queue_depth_by_pool(
    db: AsyncSession,
) -> dict[str, int]:
    """Get current queue depth grouped by agent pool.
    
    Returns:
        Dictionary mapping pool_id to queue depth
    """
    from app.db.models import RunJob, Run, Procedure
    
    stmt = (
        select(Run.procedure_id, Run.procedure_version, RunJob.job_id)
        .join(RunJob, Run.run_id == RunJob.run_id)
        .where(RunJob.status.in_(["queued", "retrying"]))
    )
    result = await db.execute(stmt)
    rows = result.all()
    
    # Map procedures to pools (simplified - in production, would need pool assignment metadata)
    # For now, just count total queue depth
    queue_depth: dict[str, int] = defaultdict(int)
    queue_depth["default"] = len(rows)
    
    return dict(queue_depth)


async def evaluate_autoscaling_decision(
    db: AsyncSession,
    pool_id: str,
    current_instances: int,
    policy: dict[str, Any] | None = None,
) -> tuple[str, int, str]:
    """Evaluate whether to scale up, down, or maintain current capacity.
    
    Args:
        db: Database session
        pool_id: Agent pool ID
        current_instances: Current number of instances in the pool
        policy: Autoscaling policy config (uses DEFAULT_POLICY if None)
    
    Returns:
        Tuple of (decision, target_instances, reason)
        decision: "scale_up" | "scale_down" | "no_change"
        target_instances: Recommended target instance count
        reason: Human-readable explanation
    """
    policy = policy or DEFAULT_POLICY
    
    if not policy.get("enabled", True):
        return "no_change", current_instances, "Autoscaling disabled"
    
    # Check saturation events
    saturation_count = await check_pool_saturation_events(
        db,
        pool_id,
        window_minutes=policy.get("saturation_window_minutes", 5),
    )
    
    # Check queue depth
    queue_depths = await get_queue_depth_by_pool(db)
    queue_depth = queue_depths.get(pool_id, 0)
    
    saturation_threshold = policy.get("saturation_threshold", 3)
    queue_threshold = policy.get("queue_depth_threshold", 10)
    min_instances = policy.get("min_instances", 1)
    max_instances = policy.get("max_instances", 10)
    scale_up_increment = policy.get("scale_up_increment", 1)
    hysteresis_factor = policy.get("hysteresis_factor", 0.8)
    
    # Scale-up conditions
    if saturation_count >= saturation_threshold or queue_depth >= queue_threshold:
        target = min(current_instances + scale_up_increment, max_instances)
        if target > current_instances:
            reason = (
                f"Pool saturated: {saturation_count} saturation events in window "
                f"(threshold: {saturation_threshold}), queue depth: {queue_depth} "
                f"(threshold: {queue_threshold})"
            )
            return "scale_up", target, reason
    
    # Scale-down conditions (hysteresis to prevent flapping)
    scale_down_saturation_threshold = int(saturation_threshold * hysteresis_factor)
    scale_down_queue_threshold = int(queue_threshold * hysteresis_factor)
    
    if saturation_count <= scale_down_saturation_threshold and queue_depth <= scale_down_queue_threshold:
        target = max(current_instances - 1, min_instances)
        if target < current_instances:
            reason = (
                f"Pool underutilized: {saturation_count} saturation events "
                f"(<= {scale_down_saturation_threshold}), queue depth: {queue_depth} "
                f"(<= {scale_down_queue_threshold})"
            )
            return "scale_down", target, reason
    
    return "no_change", current_instances, "Metrics within normal operating range"


async def request_pool_scale_action(
    pool_id: str,
    target_instances: int,
    reason: str,
) -> bool:
    """Request a scaling action from the infrastructure provider.
    
    This is a placeholder that should be integrated with your actual infrastructure
    provisioning system (K8s HPA, AWS Auto Scaling, agent spawn API, etc.).
    
    Args:
        pool_id: Agent pool to scale
        target_instances: Desired instance count
        reason: Explanation for the scaling action
    
    Returns:
        True if scaling request was successful, False otherwise
    """
    # Emit metric for monitoring
    try:
        from app.utils.metrics import metrics
        metrics.set_gauge(
            "autoscaler_target_instances",
            float(target_instances),
            labels={"pool_id": pool_id}
        )
    except Exception:
        pass
    
    # TODO: Integrate with actual infrastructure provider
    # Examples:
    # - Kubernetes HPA: PATCH deployment replicas
    # - AWS ECS: UpdateService(desiredCount=target_instances)
    # - Custom agent spawn API: POST /agents/pools/{pool_id}/scale
    
    logger.info(
        "Autoscaler recommendation for pool %s: target_instances=%d (reason: %s)",
        pool_id,
        target_instances,
        reason,
    )
    
    # For now, just log the recommendation
    # Return True to indicate the recommendation was generated successfully
    return True


async def run_autoscaler_evaluation(
    db: AsyncSession,
    pool_id: str,
    current_instances: int,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a complete autoscaling evaluation and potentially trigger scaling actions.
    
    Args:
        db: Database session
        pool_id: Agent pool to evaluate
        current_instances: Current number of instances
        policy: Optional autoscaling policy override
    
    Returns:
        Evaluation result with decision, target, and metrics
    """
    decision, target, reason = await evaluate_autoscaling_decision(
        db,
        pool_id,
        current_instances,
        policy,
    )
    
    result = {
        "pool_id": pool_id,
        "current_instances": current_instances,
        "decision": decision,
        "target_instances": target,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    if decision != "no_change":
        success = await request_pool_scale_action(pool_id, target, reason)
        result["scale_requested"] = success
    else:
        result["scale_requested"] = False
    
    return result
