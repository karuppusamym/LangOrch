"""Tests for secrets service."""

from __future__ import annotations

import os
import pytest

from app.services.secrets_service import (
    EnvironmentSecretsProvider,
    SecretsManager,
    configure_secrets_provider,
    get_secrets_manager,
    _secrets_manager,
)


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
