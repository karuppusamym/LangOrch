from __future__ import annotations

from types import SimpleNamespace

from app.config import settings
from app.main import _apply_config_sync_rows, _apply_llm_api_key_secret


def test_apply_config_sync_rows_updates_settings(monkeypatch):
    original_debug = settings.DEBUG
    try:
        monkeypatch.setattr(settings, "DEBUG", False)

        reload_count = _apply_config_sync_rows([("DEBUG", "true")])

        assert reload_count == 1
        assert settings.DEBUG is True
    finally:
        monkeypatch.setattr(settings, "DEBUG", original_debug)


def test_apply_config_sync_rows_logs_malformed_json(caplog):
    caplog.set_level("WARNING")

    reload_count = _apply_config_sync_rows([("DEBUG", "{not-json")])

    assert reload_count == 0
    assert "Skipping malformed config override DEBUG" in caplog.text


def test_apply_llm_api_key_secret_updates_setting(monkeypatch):
    original_key = settings.LLM_API_KEY
    try:
        monkeypatch.setattr(settings, "LLM_API_KEY", None)

        changed = _apply_llm_api_key_secret(
            SimpleNamespace(encrypted_value="ciphertext"),
            lambda encrypted: "decrypted-secret",
        )

        assert changed is True
        assert settings.LLM_API_KEY == "decrypted-secret"
    finally:
        monkeypatch.setattr(settings, "LLM_API_KEY", original_key)


def test_apply_llm_api_key_secret_logs_missing_value(caplog):
    caplog.set_level("WARNING")

    changed = _apply_llm_api_key_secret(SimpleNamespace(encrypted_value=None), lambda encrypted: encrypted)

    assert changed is False
    assert "Secret entry LLM_API_KEY is missing encrypted_value" in caplog.text


def test_apply_llm_api_key_secret_logs_decrypt_failure(caplog):
    caplog.set_level("WARNING")

    def _fail(_encrypted: str) -> str:
        raise RuntimeError("boom")

    changed = _apply_llm_api_key_secret(SimpleNamespace(encrypted_value="ciphertext"), _fail)

    assert changed is False
    assert "Failed to decrypt secret LLM_API_KEY" in caplog.text