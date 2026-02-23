"""Role-gating FastAPI dependencies.

Usage::

    from app.auth.roles import require_role

    @router.post("/runs", dependencies=[Depends(require_role("operator"))])
    async def create_run(...): ...

    # Or inject principal for audit logging:
    @router.post("/approvals/{id}/decision")
    async def decide(
        ...,
        principal: Principal = Depends(require_role("approver")),
    ): ...
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, status

from app.auth.deps import Principal, get_current_user

logger = logging.getLogger("langorch.auth")


def require_role(role: str):
    """Return a FastAPI dependency that enforces *role* (or higher).

    When ``AUTH_ENABLED=false`` the anonymous admin always passes.
    """

    async def _check(principal: Principal = Depends(get_current_user)) -> Principal:
        if not principal.has_role(role):
            logger.warning(
                "Access denied — user '%s' (roles=%s) needs role '%s'",
                principal.identity,
                principal.roles,
                role,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' or higher is required",
            )
        return principal

    return _check
