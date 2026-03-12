"""Tests for secrets service."""

from __future__ import annotations

import base64
import os
import pytest

from app.db.engine import async_session
from app.db.models import SecretEntry

from app.services.secrets_service import (
    CatalogAwareSecretsProvider,
    EnvironmentSecretsProvider,
    SecretsManager,
    configure_secrets_provider,
    get_secrets_manager,
    _secrets_manager,
    provider_from_config,
)


class TestSecretsApiCryptoHelpers:
    def test_encrypt_requires_encryption_key(self, monkeypatch):
        from app.api.secrets import _encrypt

        monkeypatch.delenv("SECRETS_ENCRYPTION_KEY", raising=False)

        with pytest.raises(ValueError, match="SECRETS_ENCRYPTION_KEY must be configured"):
            _encrypt("super-secret")

    def test_decrypt_legacy_base64_without_key(self, monkeypatch):
        from app.api.secrets import _decrypt

        monkeypatch.delenv("SECRETS_ENCRYPTION_KEY", raising=False)

        decoded = _decrypt(base64.b64encode(b"legacy-secret").decode())

        assert decoded == "legacy-secret"

    def test_encrypt_decrypt_round_trip_with_fernet_key(self, monkeypatch):
        pytest.importorskip("cryptography.fernet")
        from cryptography.fernet import Fernet
        from app.api.secrets import _decrypt, _encrypt

        monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())

        encrypted = _encrypt("fresh-secret")

        assert encrypted != "fresh-secret"
        assert _decrypt(encrypted) == "fresh-secret"


class TestEnvironmentSecretsProvider:
    """Test env var based secrets provider."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up and tear down test env vars."""
        os.environ["LANGORCH_SECRET_TEST_KEY"] = "test_value_123"
        os.environ["LANGORCH_SECRET_DB_PASS"] = "db_password_456"
        yield
        os.environ.pop("LANGORCH_SECRET_TEST_KEY", None)
        os.environ.pop("LANGORCH_SECRET_DB_PASS", None)

    @pytest.mark.asyncio
    async def test_get_existing_secret(self):
        provider = EnvironmentSecretsProvider()
        value = await provider.get_secret("TEST_KEY")
        assert value == "test_value_123"

    @pytest.mark.asyncio
    async def test_get_existing_secret_case_insensitive_input(self):
        provider = EnvironmentSecretsProvider()
        value = await provider.get_secret("test_key")
        assert value == "test_value_123"

    @pytest.mark.asyncio
    async def test_get_missing_secret(self):
        provider = EnvironmentSecretsProvider()
        value = await provider.get_secret("NONEXISTENT")
        assert value is None

    @pytest.mark.asyncio
    async def test_list_secrets(self):
        provider = EnvironmentSecretsProvider()
        secrets = await provider.list_secrets()
        assert "test_key" in secrets
        assert "db_pass" in secrets

    @pytest.mark.asyncio
    async def test_custom_prefix(self):
        os.environ["MYAPP_SECRET_CUSTOM"] = "custom_value"
        try:
            provider = EnvironmentSecretsProvider(prefix="MYAPP_SECRET_")
            value = await provider.get_secret("CUSTOM")
            assert value == "custom_value"
        finally:
            os.environ.pop("MYAPP_SECRET_CUSTOM", None)


class TestSecretsManager:
    """Test the SecretsManager wrapper."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        os.environ["LANGORCH_SECRET_KEY_A"] = "val_a"
        os.environ["LANGORCH_SECRET_KEY_B"] = "val_b"
        yield
        os.environ.pop("LANGORCH_SECRET_KEY_A", None)
        os.environ.pop("LANGORCH_SECRET_KEY_B", None)

    @pytest.mark.asyncio
    async def test_get_secret(self):
        manager = SecretsManager(provider=EnvironmentSecretsProvider())
        value = await manager.get_secret("KEY_A")
        assert value == "val_a"

    @pytest.mark.asyncio
    async def test_get_secrets_bulk(self):
        manager = SecretsManager(provider=EnvironmentSecretsProvider())
        secrets = await manager.get_secrets(["KEY_A", "KEY_B", "MISSING"])
        assert secrets["KEY_A"] == "val_a"
        assert secrets["KEY_B"] == "val_b"
        assert "MISSING" not in secrets

    @pytest.mark.asyncio
    async def test_list_secrets(self):
        manager = SecretsManager(provider=EnvironmentSecretsProvider())
        keys = await manager.list_secrets()
        assert "key_a" in keys
        assert "key_b" in keys


class TestGlobalSecretsManager:
    """Test the global instance pattern."""

    def setup_method(self):
        """Reset global instance."""
        import app.services.secrets_service as mod
        mod._secrets_manager = None

    @pytest.mark.asyncio
    async def test_get_secrets_manager_default(self):
        manager = get_secrets_manager()
        assert manager is not None
        assert isinstance(manager.provider, EnvironmentSecretsProvider)

    @pytest.mark.asyncio
    async def test_configure_secrets_provider(self):
        custom_provider = EnvironmentSecretsProvider(prefix="CUSTOM_")
        configure_secrets_provider(custom_provider)
        manager = get_secrets_manager()
        assert manager.provider is custom_provider

    @pytest.mark.asyncio
    async def test_singleton_behavior(self):
        m1 = get_secrets_manager()
        m2 = get_secrets_manager()
        assert m1 is m2


class TestCatalogAwareSecretsProvider:
    @pytest.fixture(autouse=True)
    def reset_global(self):
        import app.services.secrets_service as mod

        mod._secrets_manager = None

    @pytest.fixture
    def fernet_key(self, monkeypatch):
        pytest.importorskip("cryptography.fernet")
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", key)
        return key

    @pytest.mark.asyncio
    async def test_resolves_db_secret_from_catalog(self, fernet_key):
        from app.api.secrets import _encrypt

        async with async_session() as db:
            db.add(
                SecretEntry(
                    name="catalog_db_secret",
                    encrypted_value=_encrypt("db-secret-value"),
                    provider_hint="db",
                )
            )
            await db.commit()

        provider = provider_from_config({}, db_factory=async_session)
        manager = SecretsManager(provider=provider)

        value = await manager.get_secret("catalog_db_secret")
        assert value == "db-secret-value"

    @pytest.mark.asyncio
    async def test_resolves_env_hint_from_catalog_before_plain_env_lookup(self, monkeypatch, fernet_key):
        from app.api.secrets import _encrypt

        monkeypatch.setenv("LANGORCH_SECRET_CATALOG_ENV_SECRET", "env-secret-value")

        async with async_session() as db:
            db.add(
                SecretEntry(
                    name="catalog_env_secret",
                    encrypted_value=_encrypt("stored-fallback"),
                    provider_hint="env",
                )
            )
            await db.commit()

        provider = provider_from_config({"provider": "env_vars"}, db_factory=async_session)
        manager = SecretsManager(provider=provider)

        value = await manager.get_secret("catalog_env_secret")
        assert value == "env-secret-value"

    @pytest.mark.asyncio
    async def test_env_vars_alias_is_supported(self, monkeypatch):
        monkeypatch.setenv("LANGORCH_SECRET_ALIAS_SECRET", "alias-value")

        provider = provider_from_config({"provider": "env_vars"})
        manager = SecretsManager(provider=provider)

        value = await manager.get_secret("alias_secret")
        assert value == "alias-value"
