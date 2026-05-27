from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import Column, DateTime, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

Base = declarative_base()


class ConfigEntryModel(Base):
    __tablename__ = "operation_config_entries"

    key = Column(String(120), primary_key=True)
    payload = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime(timezone=True), nullable=False)


def _default_database_url() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DATA_DIR / 'operations.db'}"


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip() or _default_database_url()


def _read_json(path: Path) -> Any:
    if not path.exists() or path.is_dir():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


class DatabaseConfigStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.engine = create_engine(_database_url(), pool_pre_ping=True, pool_recycle=3600)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        Base.metadata.create_all(self.engine)

    def get(self, key: str) -> Any:
        clean_key = str(key or "").strip()
        if not clean_key:
            return None
        with self._lock:
            session = self.Session()
            try:
                row = session.query(ConfigEntryModel).filter(ConfigEntryModel.key == clean_key).first()
                if row is None:
                    return None
                return json.loads(str(row.payload or "null"))
            except Exception:
                return None
            finally:
                session.close()

    def set(self, key: str, value: Any) -> None:
        clean_key = str(key or "").strip()
        if not clean_key:
            return
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            session = self.Session()
            try:
                row = session.query(ConfigEntryModel).filter(ConfigEntryModel.key == clean_key).first()
                if row is None:
                    row = ConfigEntryModel(key=clean_key, payload=payload, updated_at=datetime.now(timezone.utc))
                    session.add(row)
                else:
                    row.payload = payload
                    row.updated_at = datetime.now(timezone.utc)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    def get_with_file_fallback(self, key: str, path: Path, default: Any) -> Any:
        stored = self.get(key)
        if stored is not None:
            return stored

        fallback = _read_json(path)
        if fallback is not None:
            self.set(key, fallback)
            return fallback
        if default is not None:
            self.set(key, default)
        return default


config_database_store = DatabaseConfigStore()
