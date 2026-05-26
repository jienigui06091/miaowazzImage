from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, String, Text

from services.app_database import Base, SessionLocal, init_app_database


class ImageConversationModel(Base):
    __tablename__ = "operation_image_conversations"

    id = Column(String(120), primary_key=True)
    user_id = Column(String(32), primary_key=True)
    title = Column(String(255), nullable=False, default="")
    payload = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)


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


class ImageConversationService:
    def __init__(self) -> None:
        init_app_database()

    def list(self, user_id: str) -> list[dict[str, Any]]:
        owner = str(user_id or "").strip()
        if not owner:
            return []
        session = SessionLocal()
        try:
            rows = (
                session.query(ImageConversationModel)
                .filter(ImageConversationModel.user_id == owner, ImageConversationModel.deleted_at.is_(None))
                .order_by(ImageConversationModel.updated_at.desc())
                .all()
            )
            return [_public_row(row) for row in rows]
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
                row.title = _payload_title(payload)
                row.payload = encoded
                row.updated_at = updated_at
                row.deleted_at = None
            session.commit()
            session.refresh(row)
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
            return len(rows)
        finally:
            session.close()


image_conversation_service = ImageConversationService()
