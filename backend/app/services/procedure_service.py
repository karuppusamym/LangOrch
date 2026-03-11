"""Procedures business logic."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Procedure


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_VALID_RELEASE_CHANNELS = ("dev", "qa", "prod")
_RELEASE_CHANNEL_ORDER = {"dev": 1, "qa": 2, "prod": 3}


def _sync_release_to_ckp(proc: Procedure) -> None:
    """Mirror release metadata into stored CKP JSON for consistency."""
    try:
        ckp = json.loads(proc.ckp_json) if proc.ckp_json else {}
        ckp["status"] = proc.status
        release = ckp.get("release") or {}
        release["channel"] = proc.release_channel
        release["promoted_from_version"] = proc.promoted_from_version
        release["promoted_at"] = proc.promoted_at.isoformat() if proc.promoted_at else None
        release["promoted_by"] = proc.promoted_by
        ckp["release"] = release
        proc.ckp_json = json.dumps(ckp)
    except Exception:
        # Keep relational columns authoritative if legacy/malformed JSON is encountered.
        return


async def import_procedure(db: AsyncSession, ckp: dict[str, Any], project_id: str | None = None) -> Procedure:
    """Validate minimal required fields and persist a CKP procedure."""
    procedure_id = ckp.get("procedure_id")
    version = ckp.get("version")
    if not procedure_id or not version:
        raise ValueError("CKP must contain procedure_id and version at the root.")

    proc = Procedure(
        procedure_id=procedure_id,
        version=version,
        name=ckp.get("name", procedure_id),
        status=ckp.get("status", "draft"),
        effective_date=ckp.get("effective_date"),
        description=ckp.get("description"),
        ckp_json=json.dumps(ckp),
        provenance_json=json.dumps(ckp["provenance"]) if ckp.get("provenance") else None,
        retrieval_metadata_json=json.dumps(ckp["retrieval_metadata"]) if ckp.get("retrieval_metadata") else None,
        trigger_config_json=json.dumps(ckp["trigger"]) if ckp.get("trigger") else None,
        release_channel=((ckp.get("release") or {}).get("channel") or "dev"),
        promoted_from_version=(ckp.get("release") or {}).get("promoted_from_version"),
        promoted_by=(ckp.get("release") or {}).get("promoted_by"),
        project_id=project_id,
    )
    db.add(proc)
    await db.flush()
    await db.refresh(proc)
    return proc


async def list_procedures(
    db: AsyncSession,
    project_id: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    search: str | None = None,
    metadata_search: str | None = None,
) -> list[Procedure]:
    stmt = select(Procedure).order_by(Procedure.created_at.desc())
    if project_id:
        stmt = stmt.where(Procedure.project_id == project_id)
    if status:
        stmt = stmt.where(Procedure.status == status)
    if metadata_search:
        # SQL LIKE filter directly on the JSON text column — fast path for
        # metadata-based discovery without loading all rows into Python.
        # Escape LIKE-special characters in user input to prevent wildcard injection.
        _escaped = (
            metadata_search
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        stmt = stmt.where(
            Procedure.retrieval_metadata_json.ilike(f"%{_escaped}%", escape="\\")
        )
    result = await db.execute(stmt)
    procs = list(result.scalars().all())
    if tags:
        # Post-filter: retrieval_metadata_json must contain ALL requested tags
        import json as _json
        filtered = []
        for proc in procs:
            if not proc.retrieval_metadata_json:
                continue
            try:
                meta = _json.loads(proc.retrieval_metadata_json)
                proc_tags = set(meta.get("tags") or [])
                if all(t in proc_tags for t in tags):
                    filtered.append(proc)
            except Exception:
                pass
        procs = filtered
    if search:
        # Full-text keyword search across procedure_id, name, description, and retrieval_metadata
        _kw = search.lower()
        matched = []
        for proc in procs:
            # Match against procedure_id and name
            if _kw in (proc.procedure_id or "").lower():
                matched.append(proc)
                continue
            if _kw in (proc.name or "").lower():
                matched.append(proc)
                continue
            if _kw in (proc.description or "").lower():
                matched.append(proc)
                continue
            # Match against retrieval_metadata fields: intents, domain, keywords, tags
            if proc.retrieval_metadata_json:
                try:
                    import json as _json
                    meta = _json.loads(proc.retrieval_metadata_json)
                    meta_str = " ".join([
                        str(meta.get("domain") or ""),
                        " ".join(meta.get("intents") or []),
                        " ".join(meta.get("keywords") or []),
                        " ".join(meta.get("tags") or []),
                    ]).lower()
                    if _kw in meta_str:
                        matched.append(proc)
                        continue
                except Exception:
                    pass
        procs = matched
    return procs


async def get_procedure(db: AsyncSession, procedure_id: str, version: str | None = None) -> Procedure | None:
    stmt = select(Procedure).where(Procedure.procedure_id == procedure_id)
    # Treat "latest" (or empty) as "return the newest version"
    if version and version.lower() != "latest":
        stmt = stmt.where(Procedure.version == version)
    else:
        stmt = stmt.order_by(Procedure.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().first()


async def list_versions(db: AsyncSession, procedure_id: str) -> list[Procedure]:
    stmt = (
        select(Procedure)
        .where(Procedure.procedure_id == procedure_id)
        .order_by(Procedure.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_procedure(
    db: AsyncSession,
    procedure_id: str,
    version: str,
    ckp: dict[str, Any],
) -> Procedure | None:
    proc = await get_procedure(db, procedure_id, version)
    if not proc:
        return None

    if ckp.get("procedure_id") and ckp.get("procedure_id") != procedure_id:
        raise ValueError("procedure_id in CKP does not match target procedure_id")
    if ckp.get("version") and ckp.get("version") != version:
        raise ValueError("version in CKP does not match target version")

    proc.name = ckp.get("name", proc.name)
    proc.status = ckp.get("status", proc.status)
    proc.effective_date = ckp.get("effective_date", proc.effective_date)
    proc.description = ckp.get("description", proc.description)
    proc.ckp_json = json.dumps(ckp)
    if "provenance" in ckp:
        proc.provenance_json = json.dumps(ckp["provenance"]) if ckp["provenance"] else None
    if "retrieval_metadata" in ckp:
        proc.retrieval_metadata_json = json.dumps(ckp["retrieval_metadata"]) if ckp["retrieval_metadata"] else None
    if "trigger" in ckp:
        proc.trigger_config_json = json.dumps(ckp["trigger"]) if ckp["trigger"] else None
    await db.flush()
    await db.refresh(proc)
    return proc


async def get_builder_draft(
    db: AsyncSession,
    procedure_id: str,
    version: str,
) -> tuple[Procedure | None, dict[str, Any] | None]:
    proc = await get_procedure(db, procedure_id, version)
    if not proc:
        return None, None

    if not proc.builder_draft_json:
        return proc, None

    try:
        return proc, json.loads(proc.builder_draft_json)
    except Exception as exc:
        raise ValueError(f"Stored builder draft is invalid JSON: {exc}") from exc


async def update_builder_draft(
    db: AsyncSession,
    procedure_id: str,
    version: str,
    draft: dict[str, Any],
) -> Procedure | None:
    proc = await get_procedure(db, procedure_id, version)
    if not proc:
        return None

    proc.builder_draft_json = json.dumps(draft)
    proc.builder_draft_updated_at = _utcnow()
    await db.flush()
    await db.refresh(proc)
    return proc


async def delete_procedure_version(db: AsyncSession, procedure_id: str, version: str) -> bool:
    proc = await get_procedure(db, procedure_id, version)
    if not proc:
        return False
    await db.delete(proc)
    await db.flush()
    return True


_VALID_STATUSES = frozenset({"draft", "active", "deprecated", "archived"})


async def patch_procedure_status(
    db: AsyncSession,
    procedure_id: str,
    version: str,
    new_status: str,
) -> Procedure | None:
    """Transition a procedure version's status without replacing the full CKP JSON.

    Valid values: ``draft``, ``active``, ``deprecated``, ``archived``.
    Returns the updated :class:`Procedure` or ``None`` if not found.
    Raises :class:`ValueError` for invalid status values.
    """
    if new_status not in _VALID_STATUSES:
        raise ValueError(
            f"Invalid status {new_status!r}. Must be one of: {sorted(_VALID_STATUSES)}"
        )
    proc = await get_procedure(db, procedure_id, version)
    if not proc:
        return None
    if proc.status == new_status:
        return proc  # idempotent — nothing to do
    proc.status = new_status
    # Mirror the status into the stored CKP JSON so the document stays consistent.
    try:
        ckp = json.loads(proc.ckp_json) if proc.ckp_json else {}
        ckp["status"] = new_status
        proc.ckp_json = json.dumps(ckp)
    except Exception:
        pass  # malformed JSON — leave ckp_json unchanged; status column is authoritative
    await db.flush()
    await db.refresh(proc)
    return proc


async def promote_procedure(
    db: AsyncSession,
    procedure_id: str,
    version: str,
    target_channel: str,
    promoted_by: str,
) -> tuple[Procedure | None, str | None]:
    """Promote a procedure version into a release channel.

    Returns ``(promoted_procedure, previous_channel_version)``.
    """
    if target_channel not in _VALID_RELEASE_CHANNELS:
        raise ValueError(
            f"Invalid target_channel {target_channel!r}. Must be one of: {_VALID_RELEASE_CHANNELS}"
        )

    proc = await get_procedure(db, procedure_id, version)
    if not proc:
        return None, None

    source_channel = proc.release_channel or "dev"
    if source_channel not in _RELEASE_CHANNEL_ORDER:
        source_channel = "dev"
    if _RELEASE_CHANNEL_ORDER[target_channel] < _RELEASE_CHANNEL_ORDER[source_channel]:
        raise ValueError(
            f"Cannot promote from {source_channel} to {target_channel}. Use forward channels only."
        )

    current_in_target_stmt = (
        select(Procedure)
        .where(
            Procedure.procedure_id == procedure_id,
            Procedure.release_channel == target_channel,
            Procedure.status == "active",
            Procedure.version != proc.version,
        )
        .order_by(Procedure.promoted_at.desc(), Procedure.created_at.desc())
    )
    existing_active = (await db.execute(current_in_target_stmt)).scalars().first()
    previous_channel_version = existing_active.version if existing_active else None

    if existing_active:
        existing_active.status = "deprecated"
        _sync_release_to_ckp(existing_active)

    proc.release_channel = target_channel
    proc.promoted_from_version = previous_channel_version
    proc.promoted_at = _utcnow()
    proc.promoted_by = promoted_by
    proc.status = "active"
    _sync_release_to_ckp(proc)

    # Record deployment history for audit trail
    from app.db.models import ProcedureDeploymentHistory
    deployment_record = ProcedureDeploymentHistory(
        procedure_id=procedure_id,
        action="promote",
        target_channel=target_channel,
        deployed_version=version,
        replaced_version=previous_channel_version,
        deployed_by=promoted_by,
        deployed_at=_utcnow(),
        status="success",
    )
    db.add(deployment_record)

    await db.flush()
    await db.refresh(proc)
    return proc, previous_channel_version


async def rollback_procedure(
    db: AsyncSession,
    procedure_id: str,
    version: str,
    target_channel: str,
    rolled_back_by: str,
    rollback_to_version: str | None = None,
) -> tuple[Procedure | None, str]:
    """Rollback a promoted procedure to a prior version within a release channel.

    Returns ``(restored_procedure, replaced_version)`` where ``replaced_version``
    is the currently active version being replaced by rollback.
    """
    if target_channel not in _VALID_RELEASE_CHANNELS:
        raise ValueError(
            f"Invalid target_channel {target_channel!r}. Must be one of: {_VALID_RELEASE_CHANNELS}"
        )

    current_proc = await get_procedure(db, procedure_id, version)
    if not current_proc:
        return None, ""

    resolved_current_channel = current_proc.release_channel or "dev"
    if resolved_current_channel not in _VALID_RELEASE_CHANNELS:
        resolved_current_channel = "dev"
    if resolved_current_channel != target_channel:
        raise ValueError(
            f"Cannot rollback {procedure_id}:{version} in channel {target_channel}; current version is in {resolved_current_channel}."
        )
    if current_proc.status != "active":
        raise ValueError(
            f"Rollback can only be performed from an active version. {procedure_id}:{version} is {current_proc.status}."
        )

    desired_rollback_version = rollback_to_version or current_proc.promoted_from_version
    if not desired_rollback_version:
        raise ValueError(
            "rollback_to_version is required when promoted_from_version is not available on current version."
        )
    if desired_rollback_version == current_proc.version:
        raise ValueError("rollback_to_version must differ from current version.")

    rollback_proc = await get_procedure(db, procedure_id, desired_rollback_version)
    if not rollback_proc:
        raise ValueError(
            f"Rollback target version {desired_rollback_version} not found for procedure {procedure_id}."
        )

    rollback_channel = rollback_proc.release_channel or "dev"
    if rollback_channel not in _VALID_RELEASE_CHANNELS:
        rollback_channel = "dev"
    if rollback_channel != target_channel:
        raise ValueError(
            f"Rollback target version {desired_rollback_version} is in {rollback_channel}, not {target_channel}."
        )
    if rollback_proc.status == "archived":
        raise ValueError(
            f"Rollback target version {desired_rollback_version} is archived and cannot be restored."
        )
    if rollback_proc.status == "draft":
        raise ValueError(
            f"Rollback target version {desired_rollback_version} is draft and cannot be restored."
        )

    current_proc.status = "deprecated"
    _sync_release_to_ckp(current_proc)

    rollback_proc.release_channel = target_channel
    rollback_proc.status = "active"
    rollback_proc.promoted_from_version = current_proc.version
    rollback_proc.promoted_at = _utcnow()
    rollback_proc.promoted_by = rolled_back_by
    _sync_release_to_ckp(rollback_proc)

    # Record rollback in deployment history for audit trail
    from app.db.models import ProcedureDeploymentHistory
    deployment_record = ProcedureDeploymentHistory(
        procedure_id=procedure_id,
        action="rollback",
        target_channel=target_channel,
        deployed_version=desired_rollback_version,
        replaced_version=current_proc.version,
        deployed_by=rolled_back_by,
        deployed_at=_utcnow(),
        status="success",
    )
    db.add(deployment_record)

    await db.flush()
    await db.refresh(rollback_proc)
    return rollback_proc, current_proc.version
