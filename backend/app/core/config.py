"""Application configuration management using Pydantic Settings."""

from pathlib import Path
from typing import List, Union
from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

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
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()
