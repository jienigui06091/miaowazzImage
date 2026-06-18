from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Index, String, Text
from sqlalchemy import text

from services.app_database import Base, SessionLocal, engine, init_app_database


class ImageConversationModel(Base):
    __tablename__ = "operation_image_conversations"

    id = Column(String(120), primary_key=True)
    user_id = Column(String(32), primary_key=True)
    title = Column(String(255), nullable=False, default="")
    payload = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        Index("ix_image_conversations_owner_updated", "user_id", "deleted_at", "updated_at"),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_id(value: object) -> str:
    return str(value or "").strip()[:120]


def _payload_title(payload: dict[str, Any]) -> str:
    return str(payload.get("title") or "").strip()[:255]


def _payload_updated_at(payload: dict[str, Any]) -> datetime:
    value = str(payload.get("updatedAt") or "").strip()
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            pass
    return _now()


def _public_row(row: ImageConversationModel) -> dict[str, Any]:
    try:
        payload = json.loads(str(row.payload or "{}"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _public_summary(row: ImageConversationModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title or "未命名会话",
        "createdAt": row.created_at.isoformat() if row.created_at else "",
        "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
        "turnCount": 0,
        "queued": 0,
        "running": 0,
        "lastPrompt": "",
    }


class ImageConversationService:
    def __init__(self) -> None:
        self._summary_cache: dict[tuple[str, int, str, bool], tuple[float, dict[str, Any]]] = {}
        init_app_database()
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_image_conversations_owner_updated "
                    "ON operation_image_conversations (user_id, deleted_at, updated_at DESC)"
                ))
        except Exception:
            pass

    def _cache_key(self, user_id: str, limit: int, cursor: str, summary: bool) -> tuple[str, int, str, bool]:
        return (str(user_id or "").strip(), int(limit or 30), str(cursor or ""), bool(summary))

    def _invalidate_cache(self, user_id: str) -> None:
        owner = str(user_id or "").strip()
        if not owner:
            self._summary_cache.clear()
            return
        for key in list(self._summary_cache):
            if key[0] == owner:
                self._summary_cache.pop(key, None)

    def list(self, user_id: str, *, limit: int = 30, cursor: str = "", summary: bool = True) -> dict[str, Any]:
        owner = str(user_id or "").strip()
        if not owner:
            return {"items": [], "next_cursor": ""}
        page_size = max(1, min(100, int(limit or 30)))
        cache_key = self._cache_key(owner, page_size, cursor, summary)
        if summary:
            cached = self._summary_cache.get(cache_key)
            if cached and cached[0] > time.time():
                return dict(cached[1])
        session = SessionLocal()
        try:
            columns = (
                ImageConversationModel.id,
                ImageConversationModel.user_id,
                ImageConversationModel.title,
                ImageConversationModel.created_at,
                ImageConversationModel.updated_at,
                ImageConversationModel.deleted_at,
            ) if summary else (ImageConversationModel,)
            query = session.query(*columns).filter(ImageConversationModel.user_id == owner, ImageConversationModel.deleted_at.is_(None))
            if cursor:
                try:
                    cursor_time = datetime.fromisoformat(str(cursor).replace("Z", "+00:00"))
                    query = query.filter(ImageConversationModel.updated_at < cursor_time)
                except Exception:
                    pass
            rows = query.order_by(ImageConversationModel.updated_at.desc()).limit(page_size + 1).all()
            page_rows = rows[:page_size]
            next_cursor = rows[page_size].updated_at.isoformat() if len(rows) > page_size else ""
            mapper = _public_summary if summary else _public_row
            result = {"items": [mapper(row) for row in page_rows], "next_cursor": next_cursor}
            if summary:
                self._summary_cache[cache_key] = (time.time() + 15, result)
            return result
        finally:
            session.close()

    def get(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        owner = str(user_id or "").strip()
        target_id = _clean_id(conversation_id)
        if not owner or not target_id:
            return None
        session = SessionLocal()
        try:
            row = (
                session.query(ImageConversationModel)
                .filter(ImageConversationModel.id == target_id, ImageConversationModel.user_id == owner, ImageConversationModel.deleted_at.is_(None))
                .first()
            )
            return _public_row(row) if row is not None else None
        finally:
            session.close()

    def save(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner = str(user_id or "").strip()
        conversation_id = _clean_id(payload.get("id"))
        if not owner or not conversation_id:
            raise ValueError("conversation id is required")
        now = _now()
        updated_at = _payload_updated_at(payload)
        session = SessionLocal()
        try:
            row = (
                session.query(ImageConversationModel)
                .filter(ImageConversationModel.id == conversation_id, ImageConversationModel.user_id == owner)
                .first()
            )
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if row is None:
                row = ImageConversationModel(
                    id=conversation_id,
                    user_id=owner,
                    title=_payload_title(payload),
                    payload=encoded,
                    created_at=now,
                    updated_at=updated_at,
                    deleted_at=None,
                )
                session.add(row)
            else:
                if row.deleted_at is not None:
                    raise ValueError("conversation has been deleted")
                row.title = _payload_title(payload)
                row.payload = encoded
                row.updated_at = updated_at
                row.deleted_at = None
            session.commit()
            session.refresh(row)
            self._invalidate_cache(owner)
            return _public_row(row)
        finally:
            session.close()

    def save_many(self, user_id: str, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        for payload in payloads:
            if isinstance(payload, dict):
                saved.append(self.save(user_id, payload))
        return saved

    def delete(self, user_id: str, conversation_id: str) -> bool:
        owner = str(user_id or "").strip()
        target_id = _clean_id(conversation_id)
        if not owner or not target_id:
            return False
        session = SessionLocal()
        try:
            row = (
                session.query(ImageConversationModel)
                .filter(ImageConversationModel.id == target_id, ImageConversationModel.user_id == owner, ImageConversationModel.deleted_at.is_(None))
                .first()
            )
            if row is None:
                return False
            row.deleted_at = _now()
            session.commit()
            self._invalidate_cache(owner)
            return True
        finally:
            session.close()

    def clear(self, user_id: str) -> int:
        owner = str(user_id or "").strip()
        if not owner:
            return 0
        session = SessionLocal()
        try:
            rows = (
                session.query(ImageConversationModel)
                .filter(ImageConversationModel.user_id == owner, ImageConversationModel.deleted_at.is_(None))
                .all()
            )
            now = _now()
            for row in rows:
                row.deleted_at = now
            session.commit()
            self._invalidate_cache(owner)
            return len(rows)
        finally:
            session.close()


image_conversation_service = ImageConversationService()
