from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import Column, DateTime, String, UniqueConstraint

from services.app_database import Base, SessionLocal, init_app_database
from services.config import DATA_DIR


TAGS_FILE = DATA_DIR / "image_tags.json"
_TAGS_CACHE: tuple[float, dict[str, list[str]]] | None = None
_ALL_TAGS_CACHE: tuple[float, list[str]] | None = None
CACHE_TTL_SECONDS = 30


class ImageTagModel(Base):
    __tablename__ = "operation_image_tags"

    id = Column(String(32), primary_key=True)
    image_rel = Column(String(1024), nullable=False, index=True)
    tag = Column(String(120), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (UniqueConstraint("image_rel", "tag", name="uq_operation_image_tags_rel_tag"),)


def _now() -> datetime:
    return datetime.now()


def _clean_rel(value: str) -> str:
    return str(value or "").strip().replace("\\", "/").lstrip("/")


def _clean_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(str(tag or "").strip() for tag in tags if str(tag or "").strip()))


def _session():
    init_app_database()
    _migrate_legacy_tags()
    return SessionLocal()


def _clear_cache() -> None:
    global _TAGS_CACHE, _ALL_TAGS_CACHE
    _TAGS_CACHE = None
    _ALL_TAGS_CACHE = None


_migrated_legacy_tags = False


def _migrate_legacy_tags() -> None:
    global _migrated_legacy_tags
    if _migrated_legacy_tags:
        return
    _migrated_legacy_tags = True
    if not TAGS_FILE.exists():
        return
    session = SessionLocal()
    try:
        if session.query(ImageTagModel).count() > 0:
            return
        try:
            data = json.loads(TAGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        now = _now()
        rows: list[ImageTagModel] = []
        for rel, tags in data.items():
            if not isinstance(tags, list):
                continue
            clean_rel = _clean_rel(str(rel))
            for tag in _clean_tags([str(item) for item in tags]):
                rows.append(ImageTagModel(id=uuid.uuid4().hex, image_rel=clean_rel, tag=tag, created_at=now))
        if rows:
            session.add_all(rows)
            session.commit()
    finally:
        session.close()


def load_tags() -> dict[str, list[str]]:
    global _TAGS_CACHE
    if _TAGS_CACHE and _TAGS_CACHE[0] > datetime.now().timestamp():
        return {rel: list(tags) for rel, tags in _TAGS_CACHE[1].items()}
    session = _session()
    try:
        rows = (
            session.query(ImageTagModel)
            .filter(ImageTagModel.deleted_at.is_(None))
            .order_by(ImageTagModel.created_at.asc())
            .all()
        )
        data: dict[str, list[str]] = {}
        for row in rows:
            data.setdefault(str(row.image_rel), []).append(str(row.tag))
        _TAGS_CACHE = (datetime.now().timestamp() + CACHE_TTL_SECONDS, {rel: list(tags) for rel, tags in data.items()})
        return data
    finally:
        session.close()


def get_tags(image_rel: str) -> list[str]:
    return load_tags().get(_clean_rel(image_rel), [])


def set_tags(image_rel: str, tags: list[str]) -> list[str]:
    rel = _clean_rel(image_rel)
    cleaned = _clean_tags(tags)
    if not rel:
        return []
    session = _session()
    try:
        rows = session.query(ImageTagModel).filter(ImageTagModel.image_rel == rel).all()
        by_tag = {str(row.tag): row for row in rows}
        now = _now()
        wanted = set(cleaned)
        for tag, row in by_tag.items():
            row.deleted_at = None if tag in wanted else now
        for tag in cleaned:
            if tag not in by_tag:
                session.add(ImageTagModel(id=uuid.uuid4().hex, image_rel=rel, tag=tag, created_at=now))
        session.commit()
        _clear_cache()
        return cleaned
    finally:
        session.close()


def remove_tags(image_rel: str) -> None:
    rel = _clean_rel(image_rel)
    if not rel:
        return
    session = _session()
    try:
        rows = (
            session.query(ImageTagModel)
            .filter(ImageTagModel.image_rel == rel, ImageTagModel.deleted_at.is_(None))
            .all()
        )
        now = _now()
        for row in rows:
            row.deleted_at = now
        session.commit()
        _clear_cache()
    finally:
        session.close()


def delete_tag(tag: str) -> int:
    value = str(tag or "").strip()
    if not value:
        return 0
    session = _session()
    try:
        rows = (
            session.query(ImageTagModel)
            .filter(ImageTagModel.tag == value, ImageTagModel.deleted_at.is_(None))
            .all()
        )
        now = _now()
        affected = {str(row.image_rel) for row in rows}
        for row in rows:
            row.deleted_at = now
        session.commit()
        _clear_cache()
        return len(affected)
    finally:
        session.close()


def get_all_tags() -> list[str]:
    global _ALL_TAGS_CACHE
    if _ALL_TAGS_CACHE and _ALL_TAGS_CACHE[0] > datetime.now().timestamp():
        return list(_ALL_TAGS_CACHE[1])
    session = _session()
    try:
        rows = (
            session.query(ImageTagModel.tag)
            .filter(ImageTagModel.deleted_at.is_(None))
            .distinct()
            .order_by(ImageTagModel.tag.asc())
            .all()
        )
        result = [str(row[0]) for row in rows]
        _ALL_TAGS_CACHE = (datetime.now().timestamp() + CACHE_TTL_SECONDS, list(result))
        return result
    finally:
        session.close()
