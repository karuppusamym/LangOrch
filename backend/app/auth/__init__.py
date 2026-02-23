"""AuthN/AuthZ helpers for LangOrch.

Opt-in via ``AUTH_ENABLED=true`` in settings.  When disabled (the default)
every request is treated as an authenticated *admin*, so all existing tests
and unauthenticated local usage continue to work without change.

Supported credential schemes
-----------------------------
1. ``Authorization: Bearer <jwt>``
   HS256-signed JWT issued by the ``/api/auth/token`` endpoint.
   Claims: ``sub`` (identity string), ``roles`` (list[str]).

2. ``X-API-Key: <key>``
   Static key from ``settings.API_KEYS``.
   Grants the ``operator`` role.

Role hierarchy (checked with ``require_role``)
-----------------------------------------------
``admin`` > ``operator`` > ``approver`` > ``viewer``
"""

from app.auth.deps import Principal, get_current_user
from app.auth.roles import require_role

__all__ = ["Principal", "get_current_user", "require_role"]
