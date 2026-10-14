"""Unit tests for app.core.config and app.core.settings."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.settings import settings as reexported_settings


def test_settings_defaults():
    """Verify development defaults are initialized properly."""
    assert settings.PROJECT_NAME == "PlantIQ API"
    assert settings.VERSION == "1.0.0"
    assert settings.ALGORITHM == "HS256"
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES in (30, 1440)
    assert settings.ENVIRONMENT in ("development", "dev", "test")


def test_settings_reexport():
    """Verify app.core.settings re-exports settings object."""
    assert reexported_settings is settings


def test_jwt_secret_aliasing():
    """Verify validation_alias accepts both JWT_SECRET and JWT_SECRET_KEY."""
    s1 = Settings(JWT_SECRET="test_secret_123_abc_xyz_key_str")
    assert s1.JWT_SECRET_KEY == "test_secret_123_abc_xyz_key_str"

    s2 = Settings(JWT_SECRET_KEY="test_secret_456_def_uvw_key_str")
    assert s2.JWT_SECRET_KEY == "test_secret_456_def_uvw_key_str"


def test_custom_cors_origins():
    """Verify string list parsing for CORS origins."""
    custom_settings = Settings(CORS_ORIGINS="http://localhost:3000, http://localhost:8080")
    assert custom_settings.CORS_ORIGINS == ["http://localhost:3000", "http://localhost:8080"]


def test_production_valid_configuration():
    """Verify valid production settings initialize cleanly."""
    prod_settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET="super-secret-production-jwt-key-987654321",
        SECRET_KEY="super-secret-production-app-key-987654321",
        DATABASE_URL="postgresql+psycopg://prod_user:SecureProdPass2026!@prod-db.internal:5432/plantiq_prod",
    )
    assert prod_settings.ENVIRONMENT == "production"
    assert prod_settings.JWT_SECRET_KEY == "super-secret-production-jwt-key-987654321"


def test_production_insecure_jwt_secret_rejected():
    """Verify placeholder or insecure JWT secret causes validation failure in production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET="dev_secret_key_change_in_production",
            SECRET_KEY="valid-secret-key-for-test",
            DATABASE_URL="postgresql+psycopg://user:pass@db.internal:5432/db",
        )
    assert "Production safety violation" in str(exc_info.value)
    assert "JWT_SECRET_KEY" in str(exc_info.value)


def test_production_placeholder_jwt_secret_rejected():
    """Verify placeholder token <CHANGE_ME> causes validation failure in production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET="<CHANGE_ME>",
            SECRET_KEY="valid-secret-key-for-test",
            DATABASE_URL="postgresql+psycopg://user:pass@db.internal:5432/db",
        )
    assert "Production safety violation" in str(exc_info.value)


def test_production_insecure_database_url_rejected():
    """Verify default development database URL causes validation failure in production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET="valid-prod-jwt-secret-key-12345",
            SECRET_KEY="valid-prod-app-secret-key-12345",
            DATABASE_URL="postgresql+psycopg://plantiq:plantiq_dev_password@localhost:5432/plantiq",
        )
    assert "Production safety violation" in str(exc_info.value)
    assert "database credentials" in str(exc_info.value)


def test_email_provider_api_key_loading_and_alias(monkeypatch):
    """Verify EMAIL_PROVIDER_API_KEY and alias RESEND_API_KEY are properly parsed."""
    monkeypatch.setenv("EMAIL_PROVIDER_API_KEY", "re_primary_key_123")
    s1 = Settings()
    assert s1.EMAIL_PROVIDER_API_KEY == "re_primary_key_123"

    monkeypatch.delenv("EMAIL_PROVIDER_API_KEY", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "re_alias_key_456")
    s2 = Settings()
    assert s2.EMAIL_PROVIDER_API_KEY == "re_alias_key_456"


def test_get_email_api_key_dynamic(monkeypatch):
    """Verify get_email_api_key returns configured key and strips whitespace."""
    from app.core.config import get_email_api_key, get_settings

    monkeypatch.setenv("EMAIL_PROVIDER_API_KEY", "  re_dynamic_key_789  ")
    get_settings(reload=True)

    key = get_email_api_key()
    assert key == "re_dynamic_key_789"


def test_safe_email_diagnostics_never_exposes_key(monkeypatch):
    """Verify get_email_diagnostics indicates configured status without exposing the key value."""
    from app.core.config import get_email_diagnostics, get_settings

    secret_key = "re_super_confidential_999"
    monkeypatch.setenv("EMAIL_PROVIDER_API_KEY", secret_key)
    get_settings(reload=True)

    diag = get_email_diagnostics()
    assert diag["is_configured"] is True
    assert diag["provider"] == "resend"
    # Ensure secret_key never appears anywhere in the diagnostic dictionary
    for k, v in diag.items():
        assert secret_key not in str(v)
