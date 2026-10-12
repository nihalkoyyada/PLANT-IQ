"""Database engine and session management."""

from __future__ import annotations

from typing import Optional
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base


def get_db_url(db_url: Optional[str] = None) -> str:
    """Resolve database URL from argument or environment settings."""
    if db_url:
        return db_url
    return settings.DATABASE_URL


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
