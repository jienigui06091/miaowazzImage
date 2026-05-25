from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from services.config import DATA_DIR


Base = declarative_base()


def _default_database_url() -> str:
    return f"sqlite:///{Path(DATA_DIR) / 'operations.db'}"


DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or _default_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
_INIT_LOCK = Lock()
_INITIALIZED_TABLES: set[str] = set()


def init_app_database() -> None:
    global _INITIALIZED_TABLES
    current_tables = set(Base.metadata.tables)
    if current_tables and current_tables.issubset(_INITIALIZED_TABLES):
        return
    with _INIT_LOCK:
        current_tables = set(Base.metadata.tables)
        if current_tables and current_tables.issubset(_INITIALIZED_TABLES):
            return
        Base.metadata.create_all(engine)
        _INITIALIZED_TABLES = set(Base.metadata.tables)
