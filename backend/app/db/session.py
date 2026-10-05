"""Database engine and session management."""

from __future__ import annotations

import os
from typing import Generator, Optional
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from pathlib import Path
from dotenv import load_dotenv

from app.db.base import Base

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

DEFAULT_DB_URL = "postgresql+psycopg://plantiq:plantiq_dev_password@localhost:5432/plantiq"


def get_db_url(db_url: Optional[str] = None) -> str:
    """Resolve database URL from argument or environment."""
    if db_url:
        return db_url
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    return DEFAULT_DB_URL


def create_db_engine(db_url: Optional[str] = None) -> Engine:
    """Create SQLAlchemy engine with appropriate dialect arguments."""
    url = get_db_url(db_url)
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create session factory for the engine."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Initialize database tables from SQLAlchemy metadata."""
    Base.metadata.create_all(bind=engine)

