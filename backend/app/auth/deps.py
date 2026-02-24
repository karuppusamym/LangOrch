"""FastAPI dependency: ``get_current_user``.

Returns a :class:`Principal` for the current request.

- When ``AUTH_ENABLED=false`` returns an anonymous admin so nothing breaks.
- When ``AUTH_ENABLED=true`` validates Bearer JWT or X-API-Key.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, Request, status

logger = logging.getLogger("langorch.auth")

# Role ordering — higher index = more privilege.
# Five-tier hierarchy matching the Figma design:
#   viewer < approver < operator < manager < admin
_ROLE_ORDER = ["viewer", "approver", "operator", "manager", "admin"]


@dataclass
class Principal:
    """Authenticated identity for a request."""

    identity: str
    roles: list[str] = field(default_factory=list)

    def has_role(self, role: str) -> bool:
        """Return True if this principal holds *role* or a higher role."""
        if not role:
            return True
        try:
            required_idx = _ROLE_ORDER.index(role)
        except ValueError:
            return role in self.roles
        for r in self.roles:
            try:
                if _ROLE_ORDER.index(r) >= required_idx:
                    return True
            except ValueError:
                pass
        return False


# ── Anonymous principal (used when AUTH_ENABLED=false) ────────────────────────

_ANON_ADMIN = Principal(identity="anonymous", roles=["admin"])


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _decode_jwt(token: str, secret: str) -> dict:
    """Decode and verify an HS256 JWT.  Raises HTTPException on failure."""
    try:
        import jwt  # PyJWT
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except Exception as exc:
        logger.debug("JWT decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ── Main dependency ───────────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Principal:
    """Return the authenticated :class:`Principal` for this request.

    When ``AUTH_ENABLED=false`` returns an anonymous admin immediately.
    """
    from app.config import settings  # late import to avoid circular deps

    if not settings.AUTH_ENABLED:
        if authorization and authorization.lower().startswith("bearer "):
            try:
                import jwt
                token = authorization.split(" ", 1)[1]
                payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=["HS256"])
                return Principal(
                    identity=payload.get("sub", "unknown"),
                    roles=payload.get("roles", ["viewer"])
                )
            except Exception:
                pass
        return _ANON_ADMIN

    # ── X-API-Key ────────────────────────────────────────────────
    if x_api_key:
        if x_api_key in settings.API_KEYS:
            return Principal(identity=f"api-key:{x_api_key[:8]}…", roles=["operator"])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # ── Bearer JWT ───────────────────────────────────────────────
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        payload = _decode_jwt(token, settings.AUTH_SECRET_KEY)
        identity: str = payload.get("sub", "unknown")
        roles: list[str] = payload.get("roles", ["viewer"])
        return Principal(identity=identity, roles=roles)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ── Role-checking dependency factory ─────────────────────────────────────────

def require_roles(allowed_roles: list[str]):
    """Return a FastAPI dependency that enforces role membership.

    Usage::

        @router.get("/secret", dependencies=[Depends(require_roles(["admin"]))])
        async def secret_endpoint(): ...
    """
    async def _check(user: Principal = Depends(get_current_user)) -> Principal:
        for role in allowed_roles:
            if user.has_role(role):
                return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires one of roles: {allowed_roles}",
        )
    return _check
