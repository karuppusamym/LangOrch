import pytest

from app.config import Settings


def test_debug_parses_release_to_false() -> None:
    s = Settings(DEBUG="release")
    assert s.DEBUG is False


def test_debug_parses_dev_to_true() -> None:
    s = Settings(DEBUG="dev")
    assert s.DEBUG is True


def test_debug_unrecognized_defaults_false() -> None:
    s = Settings(DEBUG="maybe")
    assert s.DEBUG is False


def test_default_auth_secret_allowed_when_auth_disabled() -> None:
    s = Settings(AUTH_ENABLED=False, SSO_ENABLED=False)
    assert s.AUTH_SECRET_KEY == "change-me-in-production-please"


def test_auth_enabled_rejects_placeholder_auth_secret() -> None:
    with pytest.raises(ValueError, match="AUTH_SECRET_KEY must be changed from the default placeholder"):
        Settings(AUTH_ENABLED=True)


def test_sso_enabled_rejects_short_auth_secret() -> None:
    with pytest.raises(ValueError, match="AUTH_SECRET_KEY must be at least 32 bytes"):
        Settings(SSO_ENABLED=True, AUTH_SECRET_KEY="short-secret")


def test_auth_enabled_accepts_strong_auth_secret() -> None:
    s = Settings(AUTH_ENABLED=True, AUTH_SECRET_KEY="x" * 32)
    assert s.AUTH_ENABLED is True


def test_auth_enabled_rejects_insecure_bootstrap_admin_password() -> None:
    with pytest.raises(ValueError, match="BOOTSTRAP_ADMIN_PASSWORD must not use the insecure placeholder"):
        Settings(
            AUTH_ENABLED=True,
            AUTH_SECRET_KEY="x" * 32,
            BOOTSTRAP_ADMIN_PASSWORD="admin123",
        )
