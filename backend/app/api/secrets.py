"""Secrets management REST API.

Provides a CRUD interface for named secrets stored in the platform database.
Secrets values are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256).

Endpoints
---------
GET    /api/secrets          — list secrets metadata (no values)  [operator+]
POST   /api/secrets          — create/upsert a secret             [admin]
GET    /api/secrets/{name}   — get metadata only (no value)       [operator+]
PUT    /api/secrets/{name}   — update value or description        [admin]
DELETE /api/secrets/{name}   — delete secret                      [admin]
"""

from __future__ import annotations

import base64
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import Principal
from app.auth.roles import require_role
from app.db.engine import get_db
from app.db.models import SecretEntry
from app.api.audit import emit_audit

logger = logging.getLogger("langorch.api.secrets")
router = APIRouter(tags=["secrets"])


# ── Fernet helpers ─────────────────────────────────────────────────────────────

def _get_fernet():
    """Build a Fernet instance from SECRETS_ENCRYPTION_KEY env var.

    If the key is not set, returns None.
    """
    raw_key = os.environ.get("SECRETS_ENCRYPTION_KEY")
    if not raw_key:
        return None
    try:
        from cryptography.fernet import Fernet  # type: ignore[import]
        # Accept either a raw 32-byte hex key or a URL-safe base64 Fernet key
        try:
            key = raw_key.encode()
            Fernet(key)
            return Fernet(key)
        except Exception:
            # try deriving from hex
            raw_bytes = bytes.fromhex(raw_key)
            encoded = base64.urlsafe_b64encode(raw_bytes[:32])
            return Fernet(encoded)
    except ImportError:
        logger.warning("cryptography package not installed — secure secret storage is unavailable")
        return None


def _decode_legacy_base64(encrypted: str) -> str:
    return base64.b64decode(encrypted).decode()


def _encrypt(value: str) -> str:
    f = _get_fernet()
    if not f:
        raise ValueError(
            "SECRETS_ENCRYPTION_KEY must be configured before storing database-backed secrets"
        )
    return f.encrypt(value.encode()).decode()


def _decrypt(encrypted: str) -> str:
    f = _get_fernet()
    if f:
        try:
            return f.decrypt(encrypted.encode()).decode()
        except Exception:
            try:
                decoded = _decode_legacy_base64(encrypted)
            except Exception:
                raise
            logger.warning(
                "Decrypting legacy base64-encoded secret without real encryption; re-save this secret after configuring SECRETS_ENCRYPTION_KEY"
            )
            return decoded
    try:
        decoded = _decode_legacy_base64(encrypted)
    except Exception as exc:
        raise ValueError(
            "SECRETS_ENCRYPTION_KEY must be configured to decrypt database-backed secrets"
        ) from exc
    logger.warning(
        "Decrypting legacy base64-encoded secret without real encryption; configure SECRETS_ENCRYPTION_KEY and rotate this secret"
    )
    return decoded


# ── Schemas ────────────────────────────────────────────────────────────────────

class SecretOut(BaseModel):
    secret_id: str
    name: str
    description: str | None
    provider_hint: str
    tags: list[str]
    created_by: str | None
    created_at: str
    updated_at: str


class SecretWithValueOut(SecretOut):
    value: str


class CreateSecretBody(BaseModel):
    name: str
    value: str
    description: str | None = None
    provider_hint: str = "db"
    tags: list[str] = []


class UpdateSecretBody(BaseModel):
    value: str | None = None
    description: str | None = None
    tags: list[str] | None = None


def _to_out(s: SecretEntry, *, include_value: bool = False) -> dict:
    tags = json.loads(s.tags_json) if s.tags_json else []
    base = {
        "secret_id": s.secret_id,
        "name": s.name,
        "description": s.description,
        "provider_hint": s.provider_hint,
        "tags": tags,
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }
    if include_value:
        base["value"] = _decrypt(s.encrypted_value)
    return base


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[SecretOut])
async def list_secrets(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("operator")),
):
    result = await db.execute(select(SecretEntry).order_by(SecretEntry.name))
    return [_to_out(s) for s in result.scalars().all()]


@router.post("", response_model=SecretOut, status_code=status.HTTP_201_CREATED)
async def create_secret(
    body: CreateSecretBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    existing = await db.execute(select(SecretEntry).where(SecretEntry.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Secret '{body.name}' already exists. Use PUT to update.")
    try:
        encrypted_value = _encrypt(body.value)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    entry = SecretEntry(
        name=body.name,
        encrypted_value=encrypted_value,
        description=body.description,
        provider_hint=body.provider_hint,
        tags_json=json.dumps(body.tags),
        created_by=principal.identity,
        updated_by=principal.identity,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    await emit_audit(
        db,
        category="secret_mgmt",
        action="create",
        actor=principal.identity,
        description=f"Created secret '{body.name}'",
        resource_type="secret",
        resource_id=body.name,
    )
    await db.commit()
    return _to_out(entry)


@router.get("/{name}", response_model=SecretOut)
async def get_secret(
    name: str,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("operator")),
):
    result = await db.execute(select(SecretEntry).where(SecretEntry.name == name))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail=f"Secret '{name}' not found")
    return _to_out(entry)


@router.put("/{name}", response_model=SecretOut)
async def update_secret(
    name: str,
    body: UpdateSecretBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    result = await db.execute(select(SecretEntry).where(SecretEntry.name == name))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail=f"Secret '{name}' not found")
    if body.value is not None:
        try:
            entry.encrypted_value = _encrypt(body.value)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    if body.description is not None:
        entry.description = body.description
    if body.tags is not None:
        entry.tags_json = json.dumps(body.tags)
    entry.updated_by = principal.identity
    await db.flush()
    await db.refresh(entry)
    await emit_audit(
        db,
        category="secret_mgmt",
        action="update",
        actor=principal.identity,
        description=f"Updated secret '{name}'",
        resource_type="secret",
        resource_id=name,
    )
    await db.commit()
    return _to_out(entry)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(
    name: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    result = await db.execute(select(SecretEntry).where(SecretEntry.name == name))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail=f"Secret '{name}' not found")
    await db.delete(entry)
    await emit_audit(
        db,
        category="secret_mgmt",
        action="delete",
        actor=principal.identity,
        description=f"Deleted secret '{name}'",
        resource_type="secret",
        resource_id=name,
    )
    await db.commit()
