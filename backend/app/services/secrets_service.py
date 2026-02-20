"""Secrets provider abstraction for secure credential management.

Supports multiple backends:
- ``env``   — Environment variables (default, zero deps)
- ``vault`` — HashiCorp Vault KV v1/v2 via ``hvac``; token or AppRole auth
- ``aws``   — AWS Secrets Manager via ``boto3``
- ``azure`` — Azure Key Vault via ``azure-keyvault-secrets`` + ``azure-identity``

All providers are optional-dep based: failing import raises ``ImportError`` with
an actionable install hint rather than crashing at import time.

A ``CachingSecretsProvider`` wrapper adds in-memory TTL caching on top of any
provider to reduce round-trips during a single run.

Use ``provider_from_config(config: dict)`` to build the right provider from a
``global_config.secrets_config`` dict.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("langorch.secrets")



# ── Abstract base ──────────────────────────────────────────────


class SecretsProvider(ABC):
    """Abstract base class for secrets providers."""

    @abstractmethod
    async def get_secret(self, key: str) -> str | None:
        """Retrieve a secret by key. Returns ``None`` when not found."""

    @abstractmethod
    async def list_secrets(self) -> list[str]:
        """Return a list of secret names (never values)."""


# ── Environment provider ───────────────────────────────────────


class EnvironmentSecretsProvider(SecretsProvider):
    """Read secrets from OS environment variables.

    Secret ``key`` maps to env var ``{prefix}{key.upper()}``.
    Default prefix is ``LANGORCH_SECRET_``.
    """

    def __init__(self, prefix: str = "LANGORCH_SECRET_") -> None:
        self.prefix = prefix

    async def get_secret(self, key: str) -> str | None:
        env_key = f"{self.prefix}{key.upper()}"
        value = os.environ.get(env_key)
        if value:
            logger.debug("Secret '%s' retrieved from environment", key)
        else:
            logger.debug("Secret '%s' not found in environment", key)
        return value

    async def list_secrets(self) -> list[str]:
        return [
            k[len(self.prefix):].lower()
            for k in os.environ
            if k.startswith(self.prefix)
        ]


# ── HashiCorp Vault provider ───────────────────────────────────


class VaultSecretsProvider(SecretsProvider):
    """HashiCorp Vault KV secrets engine (v1 and v2).

    Authentication options (checked in order):
    1. ``vault_token`` constructor arg
    2. ``VAULT_TOKEN`` environment variable
    3. AppRole: ``role_id`` + ``secret_id`` (or env vars
       ``VAULT_ROLE_ID`` / ``VAULT_SECRET_ID``)

    Requires ``hvac>=2.0`` — install with::

        pip install hvac
    """

    def __init__(
        self,
        vault_url: str | None = None,
        vault_token: str | None = None,
        mount_point: str = "secret",
        path_prefix: str = "langorch",
        role_id: str | None = None,
        secret_id: str | None = None,
        kv_version: int = 2,
        namespace: str | None = None,
    ) -> None:
        self.vault_url = vault_url or os.environ.get("VAULT_ADDR", "http://localhost:8200")
        self.vault_token = vault_token or os.environ.get("VAULT_TOKEN")
        self.mount_point = mount_point
        self.path_prefix = path_prefix.strip("/")
        self.role_id = role_id or os.environ.get("VAULT_ROLE_ID")
        self.secret_id = secret_id or os.environ.get("VAULT_SECRET_ID")
        self.kv_version = kv_version
        self.namespace = namespace
        self._client: Any = None

    # ── client lifecycle ───────────────────────────────────

    def _build_client(self) -> Any:
        try:
            import hvac  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "hvac is required for VaultSecretsProvider. "
                "Install with: pip install hvac"
            ) from exc

        kwargs: dict[str, Any] = {"url": self.vault_url}
        if self.namespace:
            kwargs["namespace"] = self.namespace
        if self.vault_token:
            kwargs["token"] = self.vault_token

        client = hvac.Client(**kwargs)

        # AppRole fallback when no static token
        if not self.vault_token and self.role_id and self.secret_id:
            mount = os.environ.get("VAULT_APPROLE_MOUNT", "approle")
            resp = client.auth.approle.login(
                role_id=self.role_id,
                secret_id=self.secret_id,
                mount_point=mount,
            )
            client.token = resp["auth"]["client_token"]
            logger.info("Vault AppRole authentication succeeded")

        if not client.is_authenticated():
            raise ValueError(
                "Vault authentication failed — check VAULT_TOKEN / VAULT_ROLE_ID / VAULT_SECRET_ID"
            )
        return client

    def _client_(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    # ── secret read ────────────────────────────────────────

    async def get_secret(self, key: str) -> str | None:
        try:
            client = self._client_()
            path = f"{self.path_prefix}/{key}" if self.path_prefix else key

            if self.kv_version == 2:
                resp = client.secrets.kv.v2.read_secret_version(
                    path=path, mount_point=self.mount_point
                )
                data: dict[str, Any] = resp["data"]["data"]
            else:
                resp = client.secrets.kv.v1.read_secret(
                    path=path, mount_point=self.mount_point
                )
                data = resp["data"]

            # Return "value" field, or sole field, or JSON-serialized dict
            if "value" in data:
                return str(data["value"])
            if len(data) == 1:
                return str(next(iter(data.values())))
            return json.dumps(data)

        except Exception as exc:
            logger.warning("Vault get_secret('%s') failed: %s", key, exc)
            return None

    async def list_secrets(self) -> list[str]:
        try:
            client = self._client_()
            path = self.path_prefix or ""
            if self.kv_version == 2:
                resp = client.secrets.kv.v2.list_secrets(
                    path=path, mount_point=self.mount_point
                )
            else:
                resp = client.secrets.kv.v1.list_secrets(
                    path=path, mount_point=self.mount_point
                )
            return resp.get("data", {}).get("keys", [])
        except Exception as exc:
            logger.warning("Vault list_secrets() failed: %s", exc)
            return []


# ── AWS Secrets Manager provider ──────────────────────────────


class AWSSecretsManagerProvider(SecretsProvider):
    """AWS Secrets Manager secrets provider.

    Credentials are resolved by ``boto3`` in the standard order:
    env vars → ``~/.aws/credentials`` → IAM instance role.

    ``secret_field``: when the stored secret is a JSON object, this field
    name is extracted (useful for RDS passwords etc.).  Omit to return
    the raw string / full JSON.

    LocalStack / custom endpoint supported via ``endpoint_url``.

    Requires ``boto3>=1.34`` — install with::

        pip install boto3
    """

    def __init__(
        self,
        region_name: str | None = None,
        profile_name: str | None = None,
        endpoint_url: str | None = None,
        secret_field: str | None = None,
    ) -> None:
        self.region_name = region_name or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self.profile_name = profile_name
        self.endpoint_url = endpoint_url or os.environ.get("AWS_SECRETS_ENDPOINT_URL")
        self.secret_field = secret_field
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "boto3 is required for AWSSecretsManagerProvider. "
                    "Install with: pip install boto3"
                ) from exc

            session = boto3.Session(
                region_name=self.region_name,
                profile_name=self.profile_name,
            )
            kwargs: dict[str, Any] = {}
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            self._client = session.client("secretsmanager", **kwargs)
        return self._client

    async def get_secret(self, key: str) -> str | None:
        """Fetch a secret from AWS Secrets Manager.

        The secret name stored in AWS is exactly ``key``.  If the stored
        value is JSON and ``secret_field`` is set, that field is returned.
        """
        loop = asyncio.get_event_loop()
        try:
            client = self._get_client()
            resp: dict[str, Any] = await loop.run_in_executor(
                None,
                lambda: client.get_secret_value(SecretId=key),
            )

            # AWS returns either SecretString or SecretBinary
            raw: str | bytes | None = resp.get("SecretString") or resp.get("SecretBinary")
            if raw is None:
                return None

            # Decode binary if needed
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            # Try JSON parse; extract field if configured
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    if self.secret_field:
                        val = parsed.get(self.secret_field)
                        return str(val) if val is not None else None
                    return raw  # return full JSON string
            except (json.JSONDecodeError, ValueError):
                pass  # plain string

            return raw

        except Exception as exc:
            err_name = type(exc).__name__
            if "ResourceNotFoundException" in err_name or "NoSuchEntity" in err_name:
                logger.debug("AWS secret '%s' not found", key)
            else:
                logger.warning("AWS get_secret('%s') failed: %s", key, exc)
            return None

    async def list_secrets(self) -> list[str]:
        """List secret names from AWS Secrets Manager."""
        loop = asyncio.get_event_loop()
        names: list[str] = []
        try:
            client = self._get_client()
            paginator = client.get_paginator("list_secrets")

            def _paginate() -> list[str]:
                result: list[str] = []
                for page in paginator.paginate():
                    for s in page.get("SecretList", []):
                        result.append(s["Name"])
                return result

            names = await loop.run_in_executor(None, _paginate)
        except Exception as exc:
            logger.warning("AWS list_secrets() failed: %s", exc)
        return names


# ── Azure Key Vault provider ───────────────────────────────────


class AzureKeyVaultProvider(SecretsProvider):
    """Azure Key Vault secrets provider.

    Authentication is handled by ``DefaultAzureCredential`` which resolves in
    this order: env vars (``AZURE_CLIENT_ID`` / ``AZURE_TENANT_ID`` /
    ``AZURE_CLIENT_SECRET``), workload identity, managed identity, Azure CLI.

    Secret names in Key Vault use hyphens; underscores in ``key`` are
    automatically normalised to hyphens.

    Requires::

        pip install azure-keyvault-secrets azure-identity
    """

    def __init__(
        self,
        vault_url: str | None = None,
        client_id: str | None = None,
        tenant_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self.vault_url = (
            vault_url
            or os.environ.get("AZURE_KEY_VAULT_URL")
            or os.environ.get("AZURE_KEYVAULT_URL", "")
        )
        if not self.vault_url:
            raise ValueError(
                "Azure Key Vault URL is required. "
                "Set AZURE_KEY_VAULT_URL or pass vault_url."
            )
        # Override default credential env vars when explicit args are provided
        if client_id:
            os.environ.setdefault("AZURE_CLIENT_ID", client_id)
        if tenant_id:
            os.environ.setdefault("AZURE_TENANT_ID", tenant_id)
        if client_secret:
            os.environ.setdefault("AZURE_CLIENT_SECRET", client_secret)

        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from azure.identity import DefaultAzureCredential  # type: ignore[import]
                from azure.keyvault.secrets import SecretClient  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "azure-keyvault-secrets and azure-identity are required for "
                    "AzureKeyVaultProvider. "
                    "Install with: pip install azure-keyvault-secrets azure-identity"
                ) from exc
            self._client = SecretClient(
                vault_url=self.vault_url,
                credential=DefaultAzureCredential(),
            )
        return self._client

    @staticmethod
    def _normalise_key(key: str) -> str:
        """Azure Key Vault names must use hyphens, not underscores."""
        return key.replace("_", "-")

    async def get_secret(self, key: str) -> str | None:
        normalised = self._normalise_key(key)
        loop = asyncio.get_event_loop()
        try:
            client = self._get_client()
            secret = await loop.run_in_executor(None, lambda: client.get_secret(normalised))
            logger.debug("Azure secret '%s' retrieved", key)
            return secret.value
        except Exception as exc:
            err_name = type(exc).__name__
            if "SecretNotFound" in err_name or "ResourceNotFound" in err_name:
                logger.debug("Azure secret '%s' not found", key)
            else:
                logger.warning("Azure get_secret('%s') failed: %s", key, exc)
            return None

    async def list_secrets(self) -> list[str]:
        loop = asyncio.get_event_loop()
        names: list[str] = []
        try:
            client = self._get_client()

            def _list() -> list[str]:
                return [p.name for p in client.list_properties_of_secrets()]

            names = await loop.run_in_executor(None, _list)
        except Exception as exc:
            logger.warning("Azure list_secrets() failed: %s", exc)
        return names


# ── Caching decorator ──────────────────────────────────────────


class CachingSecretsProvider(SecretsProvider):
    """In-memory TTL cache wrapper around any ``SecretsProvider``.

    Avoids repeated network round-trips during a single workflow run.
    Default TTL is 300 seconds (5 minutes).
    """

    def __init__(self, inner: SecretsProvider, ttl_seconds: int = 300) -> None:
        self.inner = inner
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[str | None, float]] = {}

    async def get_secret(self, key: str) -> str | None:
        now = time.monotonic()
        if key in self._cache:
            value, ts = self._cache[key]
            if now - ts < self.ttl:
                return value
        value = await self.inner.get_secret(key)
        self._cache[key] = (value, now)
        return value

    async def list_secrets(self) -> list[str]:
        return await self.inner.list_secrets()

    def invalidate(self, key: str | None = None) -> None:
        """Invalidate one key (or entire cache when key is None)."""
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)


# ── Factory ────────────────────────────────────────────────────


def provider_from_config(config: dict[str, Any]) -> SecretsProvider:
    """Build a ``SecretsProvider`` from a ``secrets_config`` dict.

    Supported ``type`` values and their required/optional keys:

    ``env``
        ``prefix`` (optional, default ``LANGORCH_SECRET_``)

    ``vault``
        ``vault_url``, ``vault_token`` (or VAULT_TOKEN env),
        ``mount_point``, ``path_prefix``, ``kv_version`` (1 or 2),
        ``role_id`` / ``secret_id`` for AppRole,
        ``namespace`` for HCP Vault Dedicated

    ``aws``
        ``region_name``, ``profile_name`` (optional),
        ``endpoint_url`` (optional, for LocalStack),
        ``secret_field`` (optional, extracts field from JSON secrets)

    ``azure``
        ``vault_url`` (or AZURE_KEY_VAULT_URL env),
        ``client_id``, ``tenant_id``, ``client_secret`` (optional,
        defaults to DefaultAzureCredential chain)

    ``cache_ttl`` (any type)
        When present and > 0, wraps the provider in ``CachingSecretsProvider``.
    """
    provider_type = (config.get("type") or "env").lower()
    cache_ttl: int = int(config.get("cache_ttl", 0))

    provider: SecretsProvider

    if provider_type == "env":
        provider = EnvironmentSecretsProvider(
            prefix=config.get("prefix", "LANGORCH_SECRET_")
        )

    elif provider_type in ("vault", "hashicorp_vault"):
        provider = VaultSecretsProvider(
            vault_url=config.get("vault_url"),
            vault_token=config.get("vault_token"),
            mount_point=config.get("mount_point", "secret"),
            path_prefix=config.get("path_prefix", "langorch"),
            role_id=config.get("role_id"),
            secret_id=config.get("secret_id"),
            kv_version=int(config.get("kv_version", 2)),
            namespace=config.get("namespace"),
        )

    elif provider_type in ("aws", "aws_secrets_manager"):
        provider = AWSSecretsManagerProvider(
            region_name=config.get("region_name"),
            profile_name=config.get("profile_name"),
            endpoint_url=config.get("endpoint_url"),
            secret_field=config.get("secret_field"),
        )

    elif provider_type in ("azure", "azure_key_vault"):
        provider = AzureKeyVaultProvider(
            vault_url=config.get("vault_url"),
            client_id=config.get("client_id"),
            tenant_id=config.get("tenant_id"),
            client_secret=config.get("client_secret"),
        )

    else:
        logger.warning("Unknown secrets provider type '%s', falling back to env", provider_type)
        provider = EnvironmentSecretsProvider()

    if cache_ttl > 0:
        provider = CachingSecretsProvider(provider, ttl_seconds=cache_ttl)

    return provider


# ── SecretsManager ─────────────────────────────────────────────


class SecretsManager:
    """High-level wrapper around a ``SecretsProvider``.

    Provides bulk ``get_secrets()`` and a ``list_secrets()`` pass-through.
    """

    def __init__(self, provider: SecretsProvider | None = None) -> None:
        self.provider: SecretsProvider = provider or EnvironmentSecretsProvider()

    async def get_secret(self, key: str) -> str | None:
        return await self.provider.get_secret(key)

    async def get_secrets(self, keys: list[str]) -> dict[str, str]:
        """Fetch multiple secrets, omitting keys that resolve to None."""
        result: dict[str, str] = {}
        for key in keys:
            value = await self.provider.get_secret(key)
            if value is not None:
                result[key] = value
        return result

    async def list_secrets(self) -> list[str]:
        return await self.provider.list_secrets()


# ── Global singleton ───────────────────────────────────────────


_secrets_manager: SecretsManager | None = None


def get_secrets_manager() -> SecretsManager:
    """Return (or lazily create) the global ``SecretsManager``."""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager


def configure_secrets_provider(provider: SecretsProvider) -> None:
    """Replace the global provider (used in tests and app startup)."""
    global _secrets_manager
    _secrets_manager = SecretsManager(provider=provider)


def configure_from_config(config: dict[str, Any]) -> None:
    """Build a provider from a secrets_config dict and set it as global."""
    configure_secrets_provider(provider_from_config(config))
