"""Canary deployment service for gradual rollout with traffic split and auto-rollback."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CanaryDeployment, Procedure, ProcedureDeploymentHistory

logger = logging.getLogger("langorch.canary")


async def create_canary_deployment(
    db: AsyncSession,
    procedure_id: str,
    release_channel: str,
    canary_version: str,
    stable_version: str,
    traffic_percent: int,
    created_by: str,
    route_filter: dict[str, Any] | None = None,
    rollback_config: dict[str, Any] | None = None,
) -> CanaryDeployment:
    """Create a new canary deployment configuration.
    
    Args:
        procedure_id: The procedure being canary tested
        release_channel: dev | qa | prod
        canary_version: New version being tested
        stable_version: Current stable/baseline version
        traffic_percent: Percentage of traffic to route to canary (0-100)
        created_by: User who initiated the canary
        route_filter: Optional routing filter (e.g., {"project_id": "..."})
        rollback_config: Auto-rollback thresholds (e.g., {"failure_rate_threshold": 0.05})
    
    Returns:
        The created CanaryDeployment record
    """
    if traffic_percent < 0 or traffic_percent > 100:
        raise ValueError(f"traffic_percent must be 0-100, got {traffic_percent}")
    
    if release_channel not in ("dev", "qa", "prod"):
        raise ValueError(f"Invalid release_channel {release_channel!r}")
    
    # Check that canary doesn't already exist for this procedure/channel
    existing = await get_active_canary(db, procedure_id, release_channel)
    if existing:
        raise ValueError(
            f"Active canary already exists for {procedure_id} in {release_channel}. "
            f"Complete or abort the existing canary (ID: {existing.canary_id}) first."
        )
    
    canary = CanaryDeployment(
        procedure_id=procedure_id,
        release_channel=release_channel,
        canary_version=canary_version,
        stable_version=stable_version,
        traffic_percent=traffic_percent,
        status="active",
        route_filter_json=json.dumps(route_filter) if route_filter else None,
        rollback_config_json=json.dumps(rollback_config) if rollback_config else None,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
    )
    db.add(canary)
    await db.flush()
    await db.refresh(canary)
    
    logger.info(
        "Created canary deployment: %s in %s (%d%% →  %s, baseline: %s)",
        procedure_id, release_channel, traffic_percent, canary_version, stable_version,
    )
    return canary


async def get_active_canary(
    db: AsyncSession,
    procedure_id: str,
    release_channel: str,
) -> CanaryDeployment | None:
    """Get the active canary deployment for a procedure/channel, if any."""
    stmt = (
        select(CanaryDeployment)
        .where(
            CanaryDeployment.procedure_id == procedure_id,
            CanaryDeployment.release_channel == release_channel,
            CanaryDeployment.status == "active",
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def route_canary_version(
    db: AsyncSession,
    procedure_id: str,
    release_channel: str,
    routing_key: str,
) -> str | None:
    """Determine which version to use based on canary routing.
    
    Args:
        procedure_id: The procedure being executed
        release_channel: dev | qa | prod
        routing_key: Stable routing key (e.g., run_id or trigger source) for consistent hashing
    
    Returns:
        The version to use (canary or stable), or None if no active canary
    """
    canary = await get_active_canary(db, procedure_id, release_channel)
    if not canary or canary.status != "active":
        return None
    
    # Deterministic hash-based routing for consistent experience
    hash_val = int(hashlib.md5(routing_key.encode()).hexdigest(), 16)
    bucket = hash_val % 100  # 0-99
    
    if bucket < canary.traffic_percent:
        return canary.canary_version
    else:
        return canary.stable_version


async def record_canary_run_outcome(
    db: AsyncSession,
    canary_id: str,
    run_status: str,
    version_used: str,
) -> None:
    """Record the outcome of a run executed during a canary deployment.
    
    Args:
        canary_id: The canary deployment ID
        run_status: Run status (completed | failed)
        version_used: Which version was used (canary_version or stable_version)
    """
    canary = await db.get(CanaryDeployment, canary_id)
    if not canary:
        return
    
    is_failure = run_status in ("failed", "canceled", "cancelled")
    
    if version_used == canary.canary_version:
        canary.canary_run_count += 1
        if is_failure:
            canary.canary_failure_count += 1
    elif version_used == canary.stable_version:
        canary.stable_run_count += 1
        if is_failure:
            canary.stable_failure_count += 1
    
    canary.updated_at = datetime.now(timezone.utc)
    await db.flush()
    
    # Check auto-rollback thresholds
    await check_auto_rollback(db, canary)


async def check_auto_rollback(
    db: AsyncSession,
    canary: CanaryDeployment,
) -> bool:
    """Check if canary should auto-rollback based on failure rate thresholds.
    
    Returns:
        True if rollback was triggered, False otherwise
    """
    if not canary.rollback_config_json:
        return False
    
    try:
        config = json.loads(canary.rollback_config_json)
    except Exception:
        return False
    
    threshold = config.get("failure_rate_threshold", 0.10)  # Default 10%
    min_sample_size = config.get("min_sample_size", 10)
    
    if canary.canary_run_count < min_sample_size:
        return False  # Not enough data yet
    
    canary_failure_rate = canary.canary_failure_count / max(1, canary.canary_run_count)
    stable_failure_rate = canary.stable_failure_count / max(1, canary.stable_run_count)
    
    # Rollback if canary failure rate exceeds threshold OR is significantly worse than stable
    relative_threshold = config.get("relative_degradation_threshold", 2.0)  # 2x worse
    
    should_rollback = (
        canary_failure_rate > threshold or
        (stable_failure_rate > 0 and canary_failure_rate > stable_failure_rate * relative_threshold)
    )
    
    if should_rollback:
        logger.warning(
            "Auto-rollback triggered for canary %s: canary_failure_rate=%.2f stable_failure_rate=%.2f threshold=%.2f",
            canary.canary_id,
            canary_failure_rate,
            stable_failure_rate,
            threshold,
        )
        canary.status = "rolled_back"
        canary.completed_at = datetime.now(timezone.utc)
        
        # Record rollback in deployment history
        deployment_record = ProcedureDeploymentHistory(
            procedure_id=canary.procedure_id,
            action="rollback",
            target_channel=canary.release_channel,
            deployed_version=canary.stable_version,
            replaced_version=canary.canary_version,
            deployed_by="system_auto_rollback",
            deployed_at=datetime.now(timezone.utc),
            status="success",
            reason=(
                f"Auto-rollback triggered: canary failure rate {canary_failure_rate:.2%} "
                f"exceeded threshold {threshold:.2%}"
            ),
        )
        db.add(deployment_record)
        await db.flush()
        return True
    
    return False


async def complete_canary(
    db: AsyncSession,
    canary_id: str,
    promote_canary: bool,
    completed_by: str,
) -> CanaryDeployment | None:
    """Complete a canary deployment by promoting or aborting it.
    
    Args:
        canary_id: The canary deployment to complete
        promote_canary: If True, promote canary to stable; if False, keep stable
        completed_by: User who completed the canary
    
    Returns:
        The updated canary record
    """
    canary = await db.get(CanaryDeployment, canary_id)
    if not canary:
        return None
    
    if canary.status != "active":
        raise ValueError(f"Cannot complete canary in {canary.status} status")
    
    canary.status = "completed" if promote_canary else "failed"
    canary.completed_at = datetime.now(timezone.utc)
    canary.updated_at = datetime.now(timezone.utc)
    
    if promote_canary:
        # Promote canary version to be the new stable
        from app.services import procedure_service
        
        await procedure_service.promote_procedure(
            db=db,
            procedure_id=canary.procedure_id,
            version=canary.canary_version,
            target_channel=canary.release_channel,
            promoted_by=completed_by,
        )
        logger.info(
            "Canary %s completed successfully: promoted %s to %s in %s",
            canary_id,
            canary.canary_version,
            canary.procedure_id,
            canary.release_channel,
        )
    else:
        logger.info(
            "Canary %s aborted: kept %s as stable in %s",
            canary_id,
            canary.stable_version,
            canary.release_channel,
        )
    
    await db.flush()
    await db.refresh(canary)
    return canary


async def list_canary_deployments(
    db: AsyncSession,
    procedure_id: str | None = None,
    status: str | None = None,
    release_channel: str | None = None,
) -> list[CanaryDeployment]:
    """List canary deployments with optional filters."""
    stmt = select(CanaryDeployment).order_by(CanaryDeployment.created_at.desc())
    
    if procedure_id:
        stmt = stmt.where(CanaryDeployment.procedure_id == procedure_id)
    if status:
        stmt = stmt.where(CanaryDeployment.status == status)
    if release_channel:
        stmt = stmt.where(CanaryDeployment.release_channel == release_channel)
    
    result = await db.execute(stmt)
    return list(result.scalars().all())
