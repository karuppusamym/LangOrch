"""Authentication API  login, token issuance, and identity endpoints.

Endpoints
---------
POST /api/auth/login       username + password -> JWT (always enabled)
GET  /api/auth/me          current user info from JWT
POST /api/auth/token       service-to-service token via shared secret (dev)

Five-tier role hierarchy:
    viewer < approver < operator < manager < admin
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import Principal, get_current_user
from app.db.engine import get_db

logger = logging.getLogger("langorch.auth")
router = APIRouter()


# -- Shared helpers --

def _issue_jwt(identity: str, roles: list[str], expire_minutes: int, secret: str) -> str:
    try:
        import jwt  # PyJWT
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="PyJWT is not installed. Run: pip install PyJWT",
        ) from exc
    now = datetime.now(timezone.utc)
    payload = {
        "sub": identity,
        "roles": roles,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# -- Schemas --

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenRequest(BaseModel):
    """Body for service-to-service token endpoint (dev use)."""
    identity: str
    roles: list[str] = ["viewer"]
    secret: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    identity: str
    roles: list[str]


class MeResponse(BaseModel):
    identity: str
    roles: list[str]
    user_id: str | None = None
    email: str | None = None
    full_name: str | None = None
    role: str | None = None


# -- Routes --

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with username + password",
    tags=["auth"],
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with username + password. Always available regardless of AUTH_ENABLED."""
    from app.config import settings
    from app.services.user_service import authenticate
    from app.api.audit import emit_audit

    user = await authenticate(db, body.username, body.password)
    if not user:
        await emit_audit(
            db,
            category="auth",
            action="login_failed",
            actor=body.username or "anonymous",
            description=f"Failed login attempt for username '{body.username}'",
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    expire = settings.AUTH_TOKEN_EXPIRE_MINUTES
    token = _issue_jwt(user.username, [user.role], expire, settings.AUTH_SECRET_KEY)
    logger.info("Login: user='%s' role='%s'", user.username, user.role)
    await emit_audit(
        db,
        category="auth",
        action="login",
        actor=user.username,
        description=f"User '{user.username}' logged in (role: {user.role})",
        resource_type="user",
        resource_id=user.username,
    )
    await db.commit()
    return TokenResponse(
        access_token=token,
        expires_in=expire * 60,
        identity=user.username,
        roles=[user.role],
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Return current authenticated identity",
    tags=["auth"],
)
async def me(
    principal: Principal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Return identity and roles for the current JWT / API key."""
    from app.services.user_service import get_user_by_username

    user = await get_user_by_username(db, principal.identity)
    if user:
        return MeResponse(
            identity=principal.identity,
            roles=principal.roles,
            user_id=user.user_id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
        )
    return MeResponse(identity=principal.identity, roles=principal.roles)


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Issue a signed JWT (service-to-service / dev)",
    tags=["auth"],
)
async def issue_token(body: TokenRequest) -> TokenResponse:
    """Issue a short-lived JWT using shared secret. Requires AUTH_ENABLED=true."""
    from app.config import settings

    if not settings.AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AUTH_ENABLED is false -- token endpoint is disabled",
        )
    if body.secret != settings.AUTH_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret")

    expire = settings.AUTH_TOKEN_EXPIRE_MINUTES
    token = _issue_jwt(body.identity, body.roles, expire, settings.AUTH_SECRET_KEY)
    logger.info("Issued token for identity='%s' roles=%s", body.identity, body.roles)
    return TokenResponse(
        access_token=token,
        expires_in=expire * 60,
        identity=body.identity,
        roles=body.roles,
    )
