"""User management service — CRUD with bcrypt password hashing.

Roles (ascending privilege):
    viewer < approver < operator < manager < admin

An optional bootstrap admin user can be seeded at startup when the users table
is empty. In auth/SSO-enforced deployments the bootstrap password must be set
explicitly via configuration.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User

logger = logging.getLogger("langorch.users")

VALID_ROLES = ("viewer", "approver", "operator", "manager", "admin")


def _hash_password(password: str) -> str:
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    except ImportError:
        # Fallback to passlib if bcrypt not installed directly
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return ctx.hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        import bcrypt
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ImportError:
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return ctx.verify(plain, hashed)


# ── CRUD ──────────────────────────────────────────────────────


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.user_id == user_id))
    return result.scalar_one_or_none()


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
    role: str = "viewer",
    full_name: str | None = None,
    sso_subject: str | None = None,
    sso_provider: str | None = None,
) -> User:
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of: {VALID_ROLES}")

    user = User(
        username=username,
        email=email,
        full_name=full_name,
        hashed_password=_hash_password(password),
        role=role,
        is_active=True,
        sso_subject=sso_subject,
        sso_provider=sso_provider or ("local" if not sso_subject else "sso"),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    logger.info("Created user '%s' with role '%s'", username, role)
    return user


async def update_user(
    db: AsyncSession,
    user: User,
    *,
    full_name: str | None = None,
    email: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
) -> User:
    if role is not None:
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {VALID_ROLES}")
        user.role = role
    if full_name is not None:
        user.full_name = full_name
    if email is not None:
        user.email = email
    if is_active is not None:
        user.is_active = is_active
    if password is not None:
        user.hashed_password = _hash_password(password)
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.flush()
    logger.info("Deleted user '%s'", user.username)


async def authenticate(db: AsyncSession, username: str, password: str) -> User | None:
    """Verify username + password. Returns User on success, None on failure."""
    user = await get_user_by_username(db, username)
    if not user or not user.is_active:
        return None
    if not _verify_password(password, user.hashed_password):
        return None
    return user


async def ensure_default_admin(db: AsyncSession) -> None:
    """Seed a bootstrap admin user when explicitly configured.

    In secured deployments this requires ``BOOTSTRAP_ADMIN_PASSWORD``.
    Legacy ``admin/admin123`` fallback is retained only for unauthenticated
    local development where ``DEBUG=true`` and auth/SSO are disabled.
    """
    if not settings.BOOTSTRAP_ADMIN_ENABLED:
        logger.info("Bootstrap admin seeding disabled by configuration")
        return

    username = settings.BOOTSTRAP_ADMIN_USERNAME
    result = await db.execute(select(User).where(User.username == username).limit(1))
    if result.scalar_one_or_none() is None:
        bootstrap_password = (settings.BOOTSTRAP_ADMIN_PASSWORD or "").strip() or None
        if not bootstrap_password:
            if settings.DEBUG and not settings.AUTH_ENABLED and not settings.SSO_ENABLED:
                bootstrap_password = "admin123"
                logger.warning(
                    "Seeding legacy development bootstrap admin '%s' because DEBUG=true and auth/SSO are disabled",
                    username,
                )
            else:
                logger.warning(
                    "Skipping bootstrap admin seed for '%s' because BOOTSTRAP_ADMIN_PASSWORD is not configured",
                    username,
                )
                return

        await create_user(
            db,
            username=username,
            email=settings.BOOTSTRAP_ADMIN_EMAIL,
            password=bootstrap_password,
            role="admin",
            full_name="Platform Administrator",
        )
        await db.commit()
        logger.info("Seeded bootstrap admin user '%s'", username)
