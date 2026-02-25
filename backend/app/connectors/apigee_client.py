"""Apigee OAuth2 token provider using mTLS."""

import logging
import time
from threading import Lock

import httpx

from app.config import settings

logger = logging.getLogger("langorch.connectors.apigee")

class ApigeeTokenException(Exception):
    pass

class ApigeeTokenProvider:
    """Thread-safe singleton for caching and refreshing Apigee OAuth2 tokens."""

    _instance = None
    _lock = Lock()

    def __new__(cls) -> "ApigeeTokenProvider":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._token = None
                    cls._instance._expires_at = 0.0
                    cls._instance._provider_lock = Lock()
        return cls._instance

    def get_token(self) -> str:
        """Get a valid bearer token, requesting a new one if expired."""
        now = time.time()

        # Fast path
        if self._token and now < self._expires_at:
            return self._token

        with self._provider_lock:
            # Double check inside the lock
            if self._token and now < self._expires_at:
                return self._token

            token, expires_in = self._fetch_token()
            self._token = token
            # Give a 30 second safety margin for expiration
            self._expires_at = now + max(0, expires_in - 30)
            return self._token

    def _fetch_token(self) -> tuple[str, int]:
        """Call Apigee token API using mTLS to obtain a client_credentials token."""
        url = settings.APIGEE_TOKEN_URL
        if not url:
            raise ApigeeTokenException("APIGEE_TOKEN_URL is not configured")
            
        cert_path = settings.APIGEE_CERTS_PATH
        if not cert_path:
            raise ApigeeTokenException("APIGEE_CERTS_PATH is not configured")

        client_secret = settings.APIGEE_CLIENT_SECRET
        use_case_id = settings.APIGEE_USE_CASE_ID
        
        # Try both the legacy Apigee terminology (consumer_key) and standard OAuth2 (client_id)
        client_id = settings.APIGEE_CLIENT_ID or settings.APIGEE_CONSUMER_KEY

        data = {
            "grant_type": "client_credentials"
        }
        if client_id:
            data["client_id"] = client_id
        if client_secret:
            data["client_secret"] = client_secret
        if use_case_id:
            data["use_case_id"] = use_case_id

        try:
            logger.info("Requesting new Apigee OAuth2 token using mTLS")
            
            with httpx.Client(cert=cert_path, timeout=10.0) as client:
                resp = client.post(url, data=data)
                resp.raise_for_status()
                payload = resp.json()

                token = payload.get("access_token")
                # Apigee standard is "expires_in" (seconds string or int)
                expires_in = int(payload.get("expires_in", 3600))

                if not token:
                    raise ApigeeTokenException("Token response missing access_token")

                logger.debug("Successfully acquired Apigee token (expires in %ds)", expires_in)
                return token, expires_in

        except httpx.HTTPStatusError as exc:
            logger.error("Apigee token HTTP error: %s - %s", exc.response.status_code, exc.response.text)
            raise ApigeeTokenException(f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except Exception as exc:
            logger.error("Failed to acquire Apigee token: %s", exc)
            raise ApigeeTokenException(str(exc)) from exc
