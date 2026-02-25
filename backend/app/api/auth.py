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

@router.get(
    "/sso/login",
    summary="Redirect to SSO provider for login",
    tags=["auth"],
)
async def sso_login():
    """Redirect the user to the configured SSO provider."""
    from fastapi.responses import RedirectResponse
    from app.config import settings
    import secrets
    from urllib.parse import urlencode
    
    if not settings.SSO_ENABLED:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="SSO is not enabled")
    
    state = secrets.token_urlsafe(16)
    authority = (settings.SSO_AUTHORITY or "").rstrip("/")
    auth_url = f"{authority}/oauth2/v2.0/authorize"
    
    params = {
        "client_id": settings.SSO_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.SSO_REDIRECT_URI,
        "response_mode": "query",
        "scope": "openid profile email",
        "state": state,
    }
    url = f"{auth_url}?{urlencode(params)}"
    return RedirectResponse(url)


@router.get(
    "/sso/callback",
    summary="Handle SSO provider callback",
    tags=["auth"],
)
async def sso_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db)
):
    """Exchange code for token, provision user, and redirect to frontend with JWT."""
    from fastapi.responses import RedirectResponse
    from fastapi import HTTPException
    from app.config import settings
    from app.db.models import User
    from app.services.user_service import create_user
    from sqlalchemy import select
    import httpx
    import jwt
    import secrets

    if not settings.SSO_ENABLED:
        raise HTTPException(status_code=400, detail="SSO is not enabled")
        
    authority = (settings.SSO_AUTHORITY or "").rstrip("/")
    token_url = f"{authority}/oauth2/v2.0/token"
    
    data = {
        "client_id": settings.SSO_CLIENT_ID,
        "client_secret": settings.SSO_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.SSO_REDIRECT_URI,
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        if resp.status_code != 200:
            logger.error(f"SSO token exchange failed: {resp.text}")
            raise HTTPException(status_code=400, detail="Failed to exchange authorization code")
        
        token_data = resp.json()
        
    id_token = token_data.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="No id_token received from SSO provider")
        
    payload = jwt.decode(id_token, options={"verify_signature": False})
    
    sso_sub = payload.get("sub")
    email = payload.get("email") or payload.get("preferred_username") or f"{sso_sub}@sso.local"
    name = payload.get("name") or email.split("@")[0]
    
    # ── Role Mapping Logic ──
    mapped_role = "viewer"  # Default role
    if settings.SSO_ROLE_MAPPING:
        import json
        try:
            role_map = json.loads(settings.SSO_ROLE_MAPPING)
            # Entra ID / Azure AD might send 'groups' (OIDs) or 'roles' (App Roles)
            user_groups = payload.get("groups", [])
            if not user_groups:
                user_groups = payload.get("roles", [])
            
            # Roles ordered by privilege (highest to lowest)
            role_hierarchy = ["admin", "manager", "operator", "approver", "viewer"]
            highest_privilege = "viewer"
            highest_idx = role_hierarchy.index(highest_privilege)
            
            for group in user_groups:
                if group in role_map:
                    resolved = role_map[group]
                    if resolved in role_hierarchy:
                        idx = role_hierarchy.index(resolved)
                        if idx < highest_idx:
                            highest_idx = idx
                            highest_privilege = resolved
            
            mapped_role = highest_privilege
            logger.debug(f"SSO mapping resolved role '{mapped_role}' from groups {user_groups}")
        except json.JSONDecodeError:
            logger.error("Failed to parse SSO_ROLE_MAPPING JSON. Defaulting to viewer.")
    
    if not sso_sub:
        raise HTTPException(status_code=400, detail="Invalid ID token: missing subject")
        
    result = await db.execute(select(User).where(User.sso_subject == sso_sub))
    user = result.scalar_one_or_none()
    
    if not user:
        user = await create_user(
            db,
            username=email,
            email=email,
            password=secrets.token_urlsafe(32),
            role=mapped_role,
            full_name=name,
            sso_subject=sso_sub,
            sso_provider="azure_ad"
        )
        await db.commit()
        logger.info(f"Auto-provisioned SSO user: {email} with role: {mapped_role}")
    else:
        # User already exists; keep their role perfectly in sync with Azure AD
        if user.role != mapped_role:
            logger.info(f"Syncing SSO user role: {email} ({user.role} -> {mapped_role})")
            user.role = mapped_role
            await db.commit()
            await db.refresh(user)

    expire = settings.AUTH_TOKEN_EXPIRE_MINUTES
    local_jwt = _issue_jwt(user.username, [user.role], expire, settings.AUTH_SECRET_KEY)
    
    # Redirect to frontend login page, passing the token so it can be stored
    frontend_url = "http://localhost:3000/login"
    redirect_url = f"{frontend_url}?token={local_jwt}"
    
    return RedirectResponse(url=redirect_url)
