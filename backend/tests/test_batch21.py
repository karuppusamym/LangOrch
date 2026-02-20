"""Tests for Batch 21: AWS Secrets Manager, Azure Key Vault, HashiCorp Vault
providers + CachingSecretsProvider + provider_from_config factory."""

from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.services.secrets_service import (
    AWSSecretsManagerProvider,
    AzureKeyVaultProvider,
    CachingSecretsProvider,
    EnvironmentSecretsProvider,
    SecretsManager,
    VaultSecretsProvider,
    configure_from_config,
    configure_secrets_provider,
    get_secrets_manager,
    provider_from_config,
)


# ── Helpers ────────────────────────────────────────────────────

def _make_aws_client(secret_string: str | None = None, secret_binary: bytes | None = None, raise_exc: Exception | None = None):
    """Build a mock boto3 secretsmanager client."""
    mock_client = MagicMock()
    if raise_exc:
        mock_client.get_secret_value.side_effect = raise_exc
        mock_client.get_paginator.side_effect = raise_exc
    else:
        resp: dict = {}
        if secret_string is not None:
            resp["SecretString"] = secret_string
        if secret_binary is not None:
            resp["SecretBinary"] = secret_binary
        mock_client.get_secret_value.return_value = resp

        # Mock paginator
        page = {"SecretList": [{"Name": "secret/a"}, {"Name": "secret/b"}]}
        paginator = MagicMock()
        paginator.paginate.return_value = [page]
        mock_client.get_paginator.return_value = paginator
    return mock_client


def _make_vault_client(data: dict | None = None, raise_exc: Exception | None = None):
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    if raise_exc:
        mock_client.secrets.kv.v2.read_secret_version.side_effect = raise_exc
        mock_client.secrets.kv.v2.list_secrets.side_effect = raise_exc
    else:
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": data or {"value": "vault_secret_value"}}
        }
        mock_client.secrets.kv.v2.list_secrets.return_value = {
            "data": {"keys": ["key1", "key2"]}
        }
    return mock_client


def _make_azure_client(secret_value: str | None = "azure_value", raise_exc: Exception | None = None):
    mock_client = MagicMock()
    if raise_exc:
        mock_client.get_secret.side_effect = raise_exc
        mock_client.list_properties_of_secrets.side_effect = raise_exc
    else:
        mock_secret = SimpleNamespace(value=secret_value)
        mock_client.get_secret.return_value = mock_secret
        mock_client.list_properties_of_secrets.return_value = [
            SimpleNamespace(name="az-secret-one"),
            SimpleNamespace(name="az-secret-two"),
        ]
    return mock_client


# ── AWS Secrets Manager ────────────────────────────────────────

class TestAWSSecretsManagerProvider:
    def _provider(self, mock_client) -> AWSSecretsManagerProvider:
        p = AWSSecretsManagerProvider(region_name="us-east-1")
        p._client = mock_client
        return p

    @pytest.mark.asyncio
    async def test_get_plain_string_secret(self):
        p = self._provider(_make_aws_client(secret_string="supersecret"))
        val = await p.get_secret("my/secret")
        assert val == "supersecret"

    @pytest.mark.asyncio
    async def test_get_json_secret_no_field(self):
        payload = json.dumps({"password": "p@ss", "username": "admin"})
        p = self._provider(_make_aws_client(secret_string=payload))
        val = await p.get_secret("db/creds")
        assert val == payload  # returns full JSON string

    @pytest.mark.asyncio
    async def test_get_json_secret_with_field(self):
        payload = json.dumps({"password": "p@ss", "username": "admin"})
        p = self._provider(_make_aws_client(secret_string=payload))
        p.secret_field = "password"
        val = await p.get_secret("db/creds")
        assert val == "p@ss"

    @pytest.mark.asyncio
    async def test_get_json_secret_missing_field_returns_none(self):
        payload = json.dumps({"password": "p@ss"})
        p = self._provider(_make_aws_client(secret_string=payload))
        p.secret_field = "nonexistent"
        val = await p.get_secret("db/creds")
        assert val is None

    @pytest.mark.asyncio
    async def test_get_binary_secret(self):
        p = self._provider(_make_aws_client(secret_binary=b"binary_secret"))
        val = await p.get_secret("bin/secret")
        assert val == "binary_secret"

    @pytest.mark.asyncio
    async def test_get_secret_not_found_returns_none(self):
        exc_cls = type("ResourceNotFoundException", (Exception,), {})
        p = self._provider(_make_aws_client(raise_exc=exc_cls("not found")))
        val = await p.get_secret("missing/key")
        assert val is None

    @pytest.mark.asyncio
    async def test_get_secret_error_returns_none(self):
        p = self._provider(_make_aws_client(raise_exc=Exception("network error")))
        val = await p.get_secret("any/key")
        assert val is None

    @pytest.mark.asyncio
    async def test_list_secrets(self):
        p = self._provider(_make_aws_client(secret_string="x"))
        names = await p.list_secrets()
        assert "secret/a" in names
        assert "secret/b" in names

    @pytest.mark.asyncio
    async def test_list_secrets_error_returns_empty(self):
        p = self._provider(_make_aws_client(raise_exc=Exception("list failed")))
        names = await p.list_secrets()
        assert names == []

    def test_requires_boto3(self):
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("no boto3")
            return real_import(name, *args, **kwargs)
        p = AWSSecretsManagerProvider()
        p._client = None  # ensure lazy init
        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="boto3"):
                p._get_client()


# ── Azure Key Vault ────────────────────────────────────────────

class TestAzureKeyVaultProvider:
    def _provider(self, mock_client) -> AzureKeyVaultProvider:
        p = AzureKeyVaultProvider.__new__(AzureKeyVaultProvider)
        p.vault_url = "https://myvault.vault.azure.net/"
        p._client = mock_client
        return p

    @pytest.mark.asyncio
    async def test_get_secret(self):
        p = self._provider(_make_azure_client(secret_value="azure_val"))
        val = await p.get_secret("my_secret")
        assert val == "azure_val"
        # key normalised to hyphens
        p._client.get_secret.assert_called_once_with("my-secret")

    @pytest.mark.asyncio
    async def test_underscore_normalised_to_hyphen(self):
        p = self._provider(_make_azure_client(secret_value="v"))
        await p.get_secret("db_password")
        p._client.get_secret.assert_called_once_with("db-password")

    @pytest.mark.asyncio
    async def test_get_secret_not_found_returns_none(self):
        exc_cls = type("SecretNotFound", (Exception,), {})
        p = self._provider(_make_azure_client(raise_exc=exc_cls("key not found")))
        val = await p.get_secret("missing_key")
        assert val is None

    @pytest.mark.asyncio
    async def test_get_secret_error_returns_none(self):
        p = self._provider(_make_azure_client(raise_exc=Exception("network")))
        val = await p.get_secret("key")
        assert val is None

    @pytest.mark.asyncio
    async def test_list_secrets(self):
        p = self._provider(_make_azure_client())
        names = await p.list_secrets()
        assert "az-secret-one" in names
        assert "az-secret-two" in names

    @pytest.mark.asyncio
    async def test_list_secrets_error_returns_empty(self):
        p = self._provider(_make_azure_client(raise_exc=Exception("err")))
        names = await p.list_secrets()
        assert names == []

    def test_missing_vault_url_raises(self):
        os.environ.pop("AZURE_KEY_VAULT_URL", None)
        os.environ.pop("AZURE_KEYVAULT_URL", None)
        with pytest.raises(ValueError, match="Azure Key Vault URL"):
            AzureKeyVaultProvider(vault_url=None)

    def test_requires_azure_sdk(self):
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if "azure.identity" in name or "azure.keyvault" in name:
                raise ImportError("no azure sdk")
            return real_import(name, *args, **kwargs)
        p = AzureKeyVaultProvider.__new__(AzureKeyVaultProvider)
        p.vault_url = "https://v.vault.azure.net/"
        p._client = None
        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="azure-keyvault-secrets"):
                p._get_client()


# ── HashiCorp Vault ────────────────────────────────────────────

class TestVaultSecretsProvider:
    def _provider(self, mock_client) -> VaultSecretsProvider:
        p = VaultSecretsProvider(vault_url="http://vault:8200", vault_token="root")
        p._client = mock_client
        return p

    @pytest.mark.asyncio
    async def test_get_secret_value_field(self):
        p = self._provider(_make_vault_client({"value": "my_val"}))
        val = await p.get_secret("db/pass")
        assert val == "my_val"

    @pytest.mark.asyncio
    async def test_get_secret_sole_field(self):
        p = self._provider(_make_vault_client({"token": "tok123"}))
        val = await p.get_secret("api/token")
        assert val == "tok123"

    @pytest.mark.asyncio
    async def test_get_secret_multi_field_returns_json(self):
        p = self._provider(_make_vault_client({"username": "u", "password": "p"}))
        val = await p.get_secret("creds")
        loaded = json.loads(val)
        assert loaded["username"] == "u"
        assert loaded["password"] == "p"

    @pytest.mark.asyncio
    async def test_get_secret_error_returns_none(self):
        p = self._provider(_make_vault_client(raise_exc=Exception("not found")))
        val = await p.get_secret("missing")
        assert val is None

    @pytest.mark.asyncio
    async def test_list_secrets(self):
        p = self._provider(_make_vault_client())
        keys = await p.list_secrets()
        assert "key1" in keys
        assert "key2" in keys

    @pytest.mark.asyncio
    async def test_list_secrets_error_returns_empty(self):
        p = self._provider(_make_vault_client(raise_exc=Exception("err")))
        keys = await p.list_secrets()
        assert keys == []

    def test_requires_hvac(self):
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "hvac":
                raise ImportError("no hvac")
            return real_import(name, *args, **kwargs)
        p = VaultSecretsProvider(vault_url="http://v", vault_token="t")
        p._client = None
        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="hvac"):
                p._build_client()

    def test_approle_auth_sets_token(self):
        mock_hvac = MagicMock()
        client = MagicMock()
        client.is_authenticated.return_value = True
        client.auth.approle.login.return_value = {"auth": {"client_token": "new_tok"}}
        mock_hvac.Client.return_value = client

        with patch.dict("sys.modules", {"hvac": mock_hvac}):
            p = VaultSecretsProvider(
                vault_url="http://v",
                role_id="role123",
                secret_id="secret456",
            )
            p._client = None
            built = p._build_client()
        client.auth.approle.login.assert_called_once()
        assert client.token == "new_tok"


# ── CachingSecretsProvider ─────────────────────────────────────

class TestCachingSecretsProvider:
    @pytest.fixture
    def inner(self):
        p = EnvironmentSecretsProvider()
        return p

    @pytest.mark.asyncio
    async def test_first_call_hits_inner(self):
        inner = MagicMock(spec=EnvironmentSecretsProvider)
        inner.get_secret = AsyncMock(return_value="val1")
        caching = CachingSecretsProvider(inner, ttl_seconds=60)
        result = await caching.get_secret("k")
        assert result == "val1"
        inner.get_secret.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_second_call_uses_cache(self):
        inner = MagicMock(spec=EnvironmentSecretsProvider)
        inner.get_secret = AsyncMock(return_value="val1")
        caching = CachingSecretsProvider(inner, ttl_seconds=60)
        await caching.get_secret("k")
        await caching.get_secret("k")
        assert inner.get_secret.await_count == 1  # fetched once

    @pytest.mark.asyncio
    async def test_cache_expired_refetches(self):
        inner = MagicMock(spec=EnvironmentSecretsProvider)
        inner.get_secret = AsyncMock(return_value="val1")
        caching = CachingSecretsProvider(inner, ttl_seconds=1)
        await caching.get_secret("k")
        # Manually expire cache
        caching._cache["k"] = ("val1", time.monotonic() - 2)
        await caching.get_secret("k")
        assert inner.get_secret.await_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_single_key(self):
        inner = MagicMock(spec=EnvironmentSecretsProvider)
        inner.get_secret = AsyncMock(return_value="v")
        caching = CachingSecretsProvider(inner, ttl_seconds=60)
        await caching.get_secret("k")
        caching.invalidate("k")
        assert "k" not in caching._cache

    @pytest.mark.asyncio
    async def test_invalidate_all(self):
        inner = MagicMock(spec=EnvironmentSecretsProvider)
        inner.get_secret = AsyncMock(return_value="v")
        caching = CachingSecretsProvider(inner, ttl_seconds=60)
        await caching.get_secret("a")
        await caching.get_secret("b")
        caching.invalidate()
        assert len(caching._cache) == 0

    @pytest.mark.asyncio
    async def test_caches_none_values(self):
        """None (not-found) results are also cached to avoid repeated lookups."""
        inner = MagicMock(spec=EnvironmentSecretsProvider)
        inner.get_secret = AsyncMock(return_value=None)
        caching = CachingSecretsProvider(inner, ttl_seconds=60)
        r1 = await caching.get_secret("missing")
        r2 = await caching.get_secret("missing")
        assert r1 is None
        assert r2 is None
        assert inner.get_secret.await_count == 1


# ── provider_from_config factory ──────────────────────────────

class TestProviderFromConfig:
    def test_env_default(self):
        p = provider_from_config({})
        assert isinstance(p, EnvironmentSecretsProvider)

    def test_env_explicit(self):
        p = provider_from_config({"type": "env", "prefix": "MY_SECRET_"})
        assert isinstance(p, EnvironmentSecretsProvider)
        assert p.prefix == "MY_SECRET_"

    def test_vault_type(self):
        p = provider_from_config({"type": "vault", "vault_url": "http://v", "kv_version": "1"})
        assert isinstance(p, VaultSecretsProvider)
        assert p.kv_version == 1

    def test_vault_hashicorp_alias(self):
        p = provider_from_config({"type": "hashicorp_vault", "vault_url": "http://v"})
        assert isinstance(p, VaultSecretsProvider)

    def test_aws_type(self):
        p = provider_from_config({"type": "aws", "region_name": "eu-west-1", "secret_field": "password"})
        assert isinstance(p, AWSSecretsManagerProvider)
        assert p.region_name == "eu-west-1"
        assert p.secret_field == "password"

    def test_aws_alias(self):
        p = provider_from_config({"type": "aws_secrets_manager"})
        assert isinstance(p, AWSSecretsManagerProvider)

    def test_azure_type(self):
        os.environ["AZURE_KEY_VAULT_URL"] = "https://myvault.vault.azure.net/"
        try:
            p = provider_from_config({"type": "azure"})
            assert isinstance(p, AzureKeyVaultProvider)
        finally:
            os.environ.pop("AZURE_KEY_VAULT_URL", None)

    def test_azure_alias(self):
        os.environ["AZURE_KEY_VAULT_URL"] = "https://myvault.vault.azure.net/"
        try:
            p = provider_from_config({"type": "azure_key_vault"})
            assert isinstance(p, AzureKeyVaultProvider)
        finally:
            os.environ.pop("AZURE_KEY_VAULT_URL", None)

    def test_cache_ttl_wraps_in_caching(self):
        p = provider_from_config({"type": "env", "cache_ttl": "120"})
        assert isinstance(p, CachingSecretsProvider)
        assert p.ttl == 120
        assert isinstance(p.inner, EnvironmentSecretsProvider)

    def test_zero_cache_ttl_no_wrapping(self):
        p = provider_from_config({"type": "env", "cache_ttl": "0"})
        assert isinstance(p, EnvironmentSecretsProvider)

    def test_unknown_type_falls_back_to_env(self):
        p = provider_from_config({"type": "magic_vault"})
        assert isinstance(p, EnvironmentSecretsProvider)


# ── configure_from_config ──────────────────────────────────────

class TestConfigureFromConfig:
    def test_sets_global_manager(self):
        import app.services.secrets_service as svc
        # reset to None first
        svc._secrets_manager = None
        configure_from_config({"type": "env", "prefix": "TEST_CFG_"})
        mgr = get_secrets_manager()
        assert isinstance(mgr.provider, EnvironmentSecretsProvider)
        assert mgr.provider.prefix == "TEST_CFG_"
        # cleanup
        svc._secrets_manager = None

    def test_configure_with_cache(self):
        import app.services.secrets_service as svc
        svc._secrets_manager = None
        configure_from_config({"type": "env", "cache_ttl": 60})
        mgr = get_secrets_manager()
        assert isinstance(mgr.provider, CachingSecretsProvider)
        svc._secrets_manager = None


# ── SecretsManager bulk operations ────────────────────────────

class TestSecretsManagerBulk:
    @pytest.mark.asyncio
    async def test_get_secrets_skips_none(self):
        inner = MagicMock(spec=EnvironmentSecretsProvider)
        inner.get_secret = AsyncMock(side_effect=lambda k: "v" if k == "found" else None)
        mgr = SecretsManager(provider=inner)
        result = await mgr.get_secrets(["found", "missing"])
        assert result == {"found": "v"}
        assert "missing" not in result

    @pytest.mark.asyncio
    async def test_get_secrets_empty_list(self):
        inner = MagicMock(spec=EnvironmentSecretsProvider)
        inner.get_secret = AsyncMock(return_value="v")
        mgr = SecretsManager(provider=inner)
        result = await mgr.get_secrets([])
        assert result == {}
