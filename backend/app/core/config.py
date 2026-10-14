"""Application configuration management using Pydantic Settings."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dotenv import load_dotenv
from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BASE_DIR.parent

ENV_FILE_PATHS = [
    BASE_DIR / ".env",
    ROOT_DIR / ".env",
    Path.cwd() / ".env",
]

# Synchronize python-dotenv with existing files safely at startup
for _p in ENV_FILE_PATHS:
    if _p.is_file():
        load_dotenv(_p, override=False)

INSECURE_SECRET_PATTERNS = {
    "dev_secret_key_change_in_production",
    "plantiq-secret-key-change-in-production-2026",
    "<change_me>",
    "<your_secret_key>",
    "<your_jwt_secret>",
    "change_me",
    "changeme",
    "secret",
    "password",
}


class Settings(BaseSettings):
    """Global application settings loaded from environment variables or .env file."""

    # Project metadata
    PROJECT_NAME: str = "PlantIQ API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "postgresql+psycopg://plantiq:plantiq_dev_password@localhost:5432/plantiq"

    # Redis & Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Security & Authentication
    SECRET_KEY: str = "dev_secret_key_change_in_production"
    JWT_SECRET_KEY: str = Field(
        default="plantiq-secret-key-change-in-production-2026",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "JWT_SECRET"),
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ALLOW_SELF_REGISTRATION_ROLE_SELECTION: bool = True

    # Email Delivery Configuration (Resend API & Transactional Sending)
    EMAIL_PROVIDER: str = "resend"
    EMAIL_PROVIDER_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("EMAIL_PROVIDER_API_KEY", "RESEND_API_KEY"),
    )
    EMAIL_FROM: str = Field(
        default="PlantIQ Alerts <onboarding@resend.dev>",
        validation_alias=AliasChoices("EMAIL_FROM", "SMTP_FROM_EMAIL", "RESEND_FROM_EMAIL"),
    )
    MOCK_EMAIL: bool = Field(
        default=False,
        validation_alias=AliasChoices("MOCK_EMAIL", "MOCK_SMTP"),
    )

    # Optional Legacy SMTP Fallback (Only used if explicitly configured with external host)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None

    # CORS
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:80",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Enforce strict production security checks when ENVIRONMENT is production."""
        if self.ENVIRONMENT.lower() in ("production", "prod"):
            jwt_sec = self.JWT_SECRET_KEY.strip()
            if not jwt_sec or jwt_sec.lower() in INSECURE_SECRET_PATTERNS or "change" in jwt_sec.lower():
                raise ValueError(
                    "Production safety violation: Insecure or default JWT_SECRET_KEY detected in production environment."
                )

            sec_key = self.SECRET_KEY.strip()
            if not sec_key or sec_key.lower() in INSECURE_SECRET_PATTERNS or "change" in sec_key.lower():
                raise ValueError(
                    "Production safety violation: Insecure or default SECRET_KEY detected in production environment."
                )

            db_url = self.DATABASE_URL.lower()
            if "plantiq_dev_password" in db_url or "localhost" in db_url or "127.0.0.1" in db_url:
                raise ValueError(
                    "Production safety violation: Insecure or default database credentials/host detected in production environment."
                )
        return self

    model_config = SettingsConfigDict(
        env_file=tuple(ENV_FILE_PATHS),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()


def reload_settings(env_file: Optional[Any] = "default") -> Settings:
    """Reload settings in-place so all existing imports of `settings` stay synchronized."""
    is_pytest = "PYTEST_CURRENT_TEST" in os.environ
    paths: List[Path] = []
    if env_file is None or (is_pytest and env_file == "default" and not os.getenv("EMAIL_PROVIDER_API_KEY") and not os.getenv("RESEND_API_KEY")):
        paths = []
    elif env_file == "default":
        paths = [p for p in ENV_FILE_PATHS if p.is_file()]
    elif isinstance(env_file, (list, tuple)):
        paths = [Path(p) for p in env_file if Path(p).is_file()]
    elif Path(env_file).is_file():
        paths = [Path(env_file)]

    for _p in paths:
        load_dotenv(_p, override=False)

    fresh = Settings(_env_file=tuple(paths) if paths else None)
    for field_name in Settings.model_fields:
        setattr(settings, field_name, getattr(fresh, field_name))
    return settings


def get_settings(reload: bool = False, env_file: Optional[Any] = "default") -> Settings:
    """Return application settings instance, optionally reloading from .env and environment."""
    if reload:
        reload_settings(env_file=env_file)
    return settings


def get_email_api_key() -> Optional[str]:
    """Safely return EMAIL_PROVIDER_API_KEY.

    Checks the settings singleton first. If not configured, attempts
    to reload settings in-place in case .env was saved after startup.
    Never prints, logs, or returns the key value anywhere else.
    """
    if settings.EMAIL_PROVIDER_API_KEY and str(settings.EMAIL_PROVIDER_API_KEY).strip():
        return str(settings.EMAIL_PROVIDER_API_KEY).strip()

    # Check os.environ directly
    env_key = os.getenv("EMAIL_PROVIDER_API_KEY") or os.getenv("RESEND_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # Live reload in case .env was saved on disk after server startup
    # Skip reload during test runs when environment variables have been deliberately removed
    if "PYTEST_CURRENT_TEST" not in os.environ:
        reload_settings()
        if settings.EMAIL_PROVIDER_API_KEY and str(settings.EMAIL_PROVIDER_API_KEY).strip():
            return str(settings.EMAIL_PROVIDER_API_KEY).strip()

        env_key = os.getenv("EMAIL_PROVIDER_API_KEY") or os.getenv("RESEND_API_KEY")
        return env_key.strip() if env_key else None

    return None


def get_email_diagnostics() -> Dict[str, Any]:
    """Safe diagnostic report of email delivery readiness.

    Reports only whether the API key is configured.
    NEVER logs, prints, or exposes the secret key value itself.
    """
    key = get_email_api_key()
    detected_path = None
    for _p in ENV_FILE_PATHS:
        if _p.is_file():
            detected_path = str(_p)
            break

    return {
        "is_configured": bool(key),
        "provider": settings.EMAIL_PROVIDER,
        "from_email": settings.EMAIL_FROM,
        "env_file_detected": detected_path is not None,
        "env_file_path": detected_path,
        "mock_mode_active": bool(settings.MOCK_EMAIL),
    }
