"""Users management API.

Endpoints
---------
GET    /api/users          — list all users (admin | manager)
POST   /api/users          — create user (admin)
GET    /api/users/{id}     — get user (admin | self)
PUT    /api/users/{id}     — update role / status / name (admin)
DELETE /api/users/{id}     — delete user (admin)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import Principal, get_current_user
from app.auth.roles import require_role
from app.db.engine import get_db
from app.services import user_service
from app.api.audit import emit_audit

logger = logging.getLogger("langorch.api.users")
router = APIRouter(tags=["users"])


# ── Schemas ─────────────────────────────────────────────────────

class UserOut(BaseModel):
    user_id: str
    username: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
    sso_provider: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_dt(cls, obj: object) -> "UserOut":
        from app.db.models import User
        u: User = obj  # type: ignore[assignment]
        return cls(
            user_id=u.user_id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            is_active=u.is_active,
            sso_provider=u.sso_provider,
            created_at=u.created_at.isoformat(),
            updated_at=u.updated_at.isoformat(),
        )


class CreateUserBody(BaseModel):
    username: str
    email: str
    password: str
    full_name: str | None = None
    role: str = "viewer"


class UpdateUserBody(BaseModel):
    full_name: str | None = None
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


# ── Routes ──────────────────────────────────────────────────────

@router.get("", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("manager")),
):
    users = await user_service.list_users(db)
    return [UserOut.from_orm_dt(u) for u in users]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    existing = await user_service.get_user_by_username(db, body.username)
    if existing:
        raise HTTPException(status_code=400, detail=f"Username '{body.username}' already exists")
    try:
        user = await user_service.create_user(
            db,
            username=body.username,
            email=body.email,
            password=body.password,
            role=body.role,
            full_name=body.full_name,
        )
        await emit_audit(
            db,
            category="user_mgmt",
            action="create",
            actor=principal.identity,
            description=f"Created user '{body.username}' with role '{body.role}'",
            resource_type="user",
            resource_id=body.username,
        )
        await db.commit()
        return UserOut.from_orm_dt(user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_user),
):
    # Allow admins/managers to see anyone; others can only see themselves
    user = await user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not principal.has_role("manager") and principal.identity != user.username:
        raise HTTPException(status_code=403, detail="Forbidden")
    return UserOut.from_orm_dt(user)


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UpdateUserBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    user = await user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        updated = await user_service.update_user(
            db, user,
            full_name=body.full_name,
            email=body.email,
            role=body.role,
            is_active=body.is_active,
            password=body.password,
        )
        changes = {k: v for k, v in body.model_dump(exclude_none=True).items() if k != "password"}
        await emit_audit(
            db,
            category="user_mgmt",
            action="update",
            actor=principal.identity,
            description=f"Updated user '{user.username}': {list(changes.keys())}",
            resource_type="user",
            resource_id=user.username,
            meta=changes,
        )
        await db.commit()
        return UserOut.from_orm_dt(updated)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    user = await user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Protect the last admin
    if user.role == "admin":
        from app.db.models import User as UserModel
        from sqlalchemy import select, func
        result = await db.execute(
            select(func.count()).select_from(UserModel).where(UserModel.role == "admin")
        )
        count = result.scalar_one()
        if count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin user")
    username_snapshot = user.username
    await user_service.delete_user(db, user)
    await emit_audit(
        db,
        category="user_mgmt",
        action="delete",
        actor=principal.identity,
        description=f"Deleted user '{username_snapshot}'",
        resource_type="user",
        resource_id=username_snapshot,
    )
    await db.commit()
