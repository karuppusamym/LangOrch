"""Tests for redaction utility."""

from __future__ import annotations

import pytest

from app.utils.redaction import redact_sensitive_data, _is_sensitive_key, REDACTION_PLACEHOLDER


class TestIsSensitiveKey:
    """Test the _is_sensitive_key helper."""

    @pytest.mark.parametrize("key", [
        "password", "PASSWORD", "user_password", "db_password",
        "token", "access_token", "jwt_token",
        "api_key", "api-key", "apikey", "API_KEY",
        "secret", "client_secret", "CLIENT_SECRET",
        "credential", "credentials",
        "authorization", "Authorization", "AUTHORIZATION",
        "auth", "AUTH", "auth_header",
        "private_key", "private-key", "PRIVATE_KEY",
        "access_key", "access-key", "ACCESS_KEY",
        "client_secret", "client-secret",
    ])
    def test_sensitive_keys_detected(self, key):
        assert _is_sensitive_key(key) is True, f"'{key}' should be detected as sensitive"

    @pytest.mark.parametrize("key", [
        "name", "email", "status", "count", "description",
        "node_id", "step_id", "action", "result", "message",
    ])
    def test_non_sensitive_keys_not_detected(self, key):
        assert _is_sensitive_key(key) is False, f"'{key}' should NOT be detected as sensitive"


class TestRedactSensitiveData:
    """Test the redact_sensitive_data function."""

    def test_redacts_password(self):
        data = {"user": "admin", "password": "s3cret"}
        result = redact_sensitive_data(data)
        assert result["user"] == "admin"
        assert result["password"] == REDACTION_PLACEHOLDER

    def test_redacts_nested_dict(self):
        data = {
            "config": {
                "api_key": "12345",
                "name": "test",
            }
        }
        result = redact_sensitive_data(data)
        assert result["config"]["api_key"] == REDACTION_PLACEHOLDER
        assert result["config"]["name"] == "test"

    def test_redacts_in_lists(self):
        data = [
            {"password": "secret1", "name": "a"},
            {"password": "secret2", "name": "b"},
        ]
        result = redact_sensitive_data(data)
        assert result[0]["password"] == REDACTION_PLACEHOLDER
        assert result[0]["name"] == "a"
        assert result[1]["password"] == REDACTION_PLACEHOLDER

    def test_redacts_in_tuples(self):
        data = ({"token": "abc"}, {"data": "safe"})
        result = redact_sensitive_data(data)
        assert isinstance(result, tuple)
        assert result[0]["token"] == REDACTION_PLACEHOLDER
        assert result[1]["data"] == "safe"

    def test_non_dict_passthrough(self):
        assert redact_sensitive_data("string") == "string"
        assert redact_sensitive_data(42) == 42
        assert redact_sensitive_data(None) is None
        assert redact_sensitive_data(True) is True

    def test_empty_dict(self):
        assert redact_sensitive_data({}) == {}

    def test_deeply_nested(self):
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "secret": "deep_secret",
                        "value": "ok",
                    }
                }
            }
        }
        result = redact_sensitive_data(data)
        assert result["level1"]["level2"]["level3"]["secret"] == REDACTION_PLACEHOLDER
        assert result["level1"]["level2"]["level3"]["value"] == "ok"

    def test_max_depth_protection(self):
        """Should not recurse infinitely / handle max_depth."""
        data = {"a": {"b": {"c": {"secret": "deep"}}}}
        result = redact_sensitive_data(data, max_depth=2)
        # At depth 2, inner dict should be returned as-is (not redacted)
        assert result["a"]["b"] == {"c": {"secret": "deep"}}

    def test_multiple_sensitive_keys_in_one_dict(self):
        data = {
            "api_key": "key123",
            "token": "tok456",
            "password": "pwd789",
            "name": "safe",
        }
        result = redact_sensitive_data(data)
        assert result["api_key"] == REDACTION_PLACEHOLDER
        assert result["token"] == REDACTION_PLACEHOLDER
        assert result["password"] == REDACTION_PLACEHOLDER
        assert result["name"] == "safe"

    def test_original_data_not_mutated(self):
        data = {"password": "original"}
        _ = redact_sensitive_data(data)
        assert data["password"] == "original"
