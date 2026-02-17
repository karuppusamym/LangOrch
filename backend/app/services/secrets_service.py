"""Secrets provider abstraction for secure credential management.

Supports multiple backends:
- Environment variables (default)
- HashiCorp Vault (optional)
- AWS Secrets Manager (future)
- Azure Key Vault (future)
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any
import logging

logger = logging.getLogger("langorch.secrets")


class SecretsProvider(ABC):
    """Abstract base class for secrets providers."""
    
    @abstractmethod
    async def get_secret(self, key: str) -> str | None:
        """
        Retrieve a secret by key.
        
        Args:
            key: Secret identifier
            
        Returns:
            Secret value or None if not found
        """
        pass
    
    @abstractmethod
    async def list_secrets(self) -> list[str]:
        """
        List available secret keys (not values).
        
        Returns:
            List of secret keys
        """
        pass


class EnvironmentSecretsProvider(SecretsProvider):
    """Secrets provider that reads from environment variables."""
    
    def __init__(self, prefix: str = "LANGORCH_SECRET_"):
        """
        Initialize environment secrets provider.
        
        Args:
            prefix: Environment variable prefix for secrets
        """
        self.prefix = prefix
    
    async def get_secret(self, key: str) -> str | None:
        """Get secret from environment variable."""
        env_key = f"{self.prefix}{key.upper()}"
        value = os.environ.get(env_key)
        
        if value:
            logger.debug("Retrieved secret '%s' from environment", key)
        else:
            logger.debug("Secret '%s' not found in environment", key)
        
        return value
    
    async def list_secrets(self) -> list[str]:
        """List available secrets from environment."""
        secrets = []
        for env_key in os.environ.keys():
            if env_key.startswith(self.prefix):
                # Strip prefix and lowercase
                secret_key = env_key[len(self.prefix):].lower()
                secrets.append(secret_key)
        
        return secrets


class VaultSecretsProvider(SecretsProvider):
    """Secrets provider for HashiCorp Vault (requires hvac library)."""
    
    def __init__(
        self,
        vault_url: str,
        vault_token: str | None = None,
        mount_point: str = "secret",
        path_prefix: str = "langorch",
    ):
        """
        Initialize Vault secrets provider.
        
        Args:
            vault_url: Vault server URL (e.g., http://localhost:8200)
            vault_token: Vault authentication token
            mount_point: KV secrets engine mount point
            path_prefix: Path prefix for secrets
        """
        self.vault_url = vault_url
        self.vault_token = vault_token or os.environ.get("VAULT_TOKEN")
        self.mount_point = mount_point
        self.path_prefix = path_prefix
        self._client = None
    
    def _get_client(self):
        """Lazy-load Vault client."""
        if self._client is None:
            try:
                import hvac
                self._client = hvac.Client(url=self.vault_url, token=self.vault_token)
                if not self._client.is_authenticated():
                    logger.error("Vault authentication failed")
                    raise ValueError("Vault authentication failed")
            except ImportError:
                logger.error("hvac library not installed. Install with: pip install hvac")
                raise ImportError("hvac library required for Vault secrets provider")
        
        return self._client
    
    async def get_secret(self, key: str) -> str | None:
        """Get secret from Vault."""
        try:
            client = self._get_client()
            path = f"{self.path_prefix}/{key}"
            
            # Try KV v2 first, fallback to v1
            try:
                response = client.secrets.kv.v2.read_secret_version(
                    path=path,
                    mount_point=self.mount_point,
                )
                secret_data = response["data"]["data"]
            except Exception:
                # Fallback to KV v1
                response = client.secrets.kv.v1.read_secret(
                    path=path,
                    mount_point=self.mount_point,
                )
                secret_data = response["data"]
            
            # Return the 'value' field or the entire data if single key
            if "value" in secret_data:
                return secret_data["value"]
            elif len(secret_data) == 1:
                return list(secret_data.values())[0]
            else:
                logger.warning("Secret '%s' has multiple fields, returning as dict", key)
                return str(secret_data)
        
        except Exception as exc:
            logger.warning("Failed to retrieve secret '%s' from Vault: %s", key, exc)
            return None
    
    async def list_secrets(self) -> list[str]:
        """List available secrets from Vault."""
        try:
            client = self._get_client()
            
            # List secrets at path prefix
            try:
                response = client.secrets.kv.v2.list_secrets(
                    path=self.path_prefix,
                    mount_point=self.mount_point,
                )
            except Exception:
                # Fallback to KV v1
                response = client.secrets.kv.v1.list_secrets(
                    path=self.path_prefix,
                    mount_point=self.mount_point,
                )
            
            return response.get("data", {}).get("keys", [])
        
        except Exception as exc:
            logger.warning("Failed to list secrets from Vault: %s", exc)
            return []


class SecretsManager:
    """Manager for secrets providers with fallback support."""
    
    def __init__(self, provider: SecretsProvider | None = None):
        """
        Initialize secrets manager.
        
        Args:
            provider: Secrets provider to use (defaults to EnvironmentSecretsProvider)
        """
        self.provider = provider or EnvironmentSecretsProvider()
    
    async def get_secret(self, key: str) -> str | None:
        """
        Get a secret by key.
        
        Args:
            key: Secret identifier
            
        Returns:
            Secret value or None if not found
        """
        return await self.provider.get_secret(key)
    
    async def get_secrets(self, keys: list[str]) -> dict[str, str]:
        """
        Get multiple secrets.
        
        Args:
            keys: List of secret identifiers
            
        Returns:
            Dictionary mapping keys to values (excludes not-found secrets)
        """
        secrets = {}
        for key in keys:
            value = await self.get_secret(key)
            if value is not None:
                secrets[key] = value
        
        return secrets
    
    async def list_secrets(self) -> list[str]:
        """
        List available secret keys.
        
        Returns:
            List of secret keys
        """
        return await self.provider.list_secrets()


# Global secrets manager instance
_secrets_manager: SecretsManager | None = None


def get_secrets_manager() -> SecretsManager:
    """Get or create the global secrets manager."""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager


def configure_secrets_provider(provider: SecretsProvider):
    """Configure the global secrets provider."""
    global _secrets_manager
    _secrets_manager = SecretsManager(provider=provider)
