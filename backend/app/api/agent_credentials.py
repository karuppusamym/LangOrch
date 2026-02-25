from datetime import datetime, timedelta, timezone
import jwt
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.engine import get_db
from app.config import settings
from app.services.secrets_service import get_secrets_manager

router = APIRouter(prefix="/api/agent-credentials", tags=["Agent Credentials"])

bearer_scheme = HTTPBearer()

def create_credential_grant_token(run_id: str, secret_name: str) -> str:
    """Issue a short-lived token allowing an agent to pull a specific secret."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": run_id,
        "aud": "agent_credential",
        "secret_name": secret_name,
        "iat": now,
        "exp": now + timedelta(minutes=5),  # Short-lived
    }
    return jwt.encode(payload, settings.AUTH_SECRET_KEY, algorithm="HS256")

async def verify_credential_grant(token: str) -> dict[str, Any]:
    """Verify the grant token and return the payload."""
    try:
        payload = jwt.decode(
            token,
            settings.AUTH_SECRET_KEY,
            algorithms=["HS256"],
            audience="agent_credential",
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Credential grant token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid credential grant token")

@router.get("/{secret_name}")
async def pull_credential(
    secret_name: str,
    creds: HTTPAuthorizationCredentials = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db)
):
    """
    Agents call this endpoint to exchange a grant token for the actual secret value.
    The agent must pass the token received in the step parameters.
    """
    token = creds.credentials
    payload = await verify_credential_grant(token)
    
    if payload.get("secret_name") != secret_name:
        raise HTTPException(status_code=403, detail="Token not valid for this secret")
        
    # We could also verify the run is still active (state running/queued) 
    # but the 5min expiry is usually enough protection.

    # Fetch the actual secret
    secrets_manager = get_secrets_manager()
    secret_value = await secrets_manager.get_secret(secret_name)
    
    if secret_value is None:
        raise HTTPException(status_code=404, detail=f"Secret '{secret_name}' not found")
        
    return {"value": secret_value}
