from __future__ import annotations

import hashlib
import secrets
import string
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from services.app_database import Base, SessionLocal, init_app_database
from services.user_service import QuotaRecordModel, UserModel, _new_id, _now, _public_user, user_service


class RedeemCodeModel(Base):
    __tablename__ = "operation_redeem_codes"

    id = Column(String(32), primary_key=True)
    code_hash = Column(String(128), nullable=False, unique=True, index=True)
    code_preview = Column(String(32), nullable=False, default="")
    quota_amount = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="active")
    created_by = Column(String(32), ForeignKey("operation_users.id"), nullable=True, index=True)
    redeemed_by = Column(String(32), ForeignKey("operation_users.id"), nullable=True, index=True)
    redeemed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text, nullable=False, default="")
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class RedeemRecordModel(Base):
    __tablename__ = "operation_redeem_records"

    id = Column(String(32), primary_key=True)
    code_id = Column(String(32), ForeignKey("operation_redeem_codes.id"), nullable=False, index=True)
    user_id = Column(String(32), ForeignKey("operation_users.id"), nullable=False, index=True)
    quota_amount = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("code_id", name="uq_redeem_record_code"),)


def _normalize_code(code: str) -> str:
    return "".join(ch for ch in str(code or "").strip().upper() if ch not in {" ", "\t", "\n", "\r"})


def _hash_code(code: str) -> str:
    return hashlib.sha256(_normalize_code(code).encode("utf-8")).hexdigest()


def _preview_code(code: str) -> str:
    normalized = _normalize_code(code)
    if len(normalized) <= 8:
        return normalized
    return f"{normalized[:4]}****{normalized[-4:]}"


def _generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)]
    return "-".join(parts)


def _parse_expires_at(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) == 10:
        raw = f"{raw}T23:59:59"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("过期时间格式不正确") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _status_for_code(item: RedeemCodeModel, now: datetime | None = None) -> str:
    expires_at = _as_aware(item.expires_at)
    if item.status == "active" and expires_at is not None and expires_at < (now or _now()):
        return "expired"
    return str(item.status or "active")


class RedeemCodeService:
    def __init__(self):
        init_app_database()

    @staticmethod
    def _public_code(item: RedeemCodeModel, *, code: str = "") -> dict[str, Any]:
        data = {
            "id": item.id,
            "code_preview": item.code_preview,
            "quota_amount": int(item.quota_amount or 0),
            "status": _status_for_code(item),
            "created_by": item.created_by,
            "redeemed_by": item.redeemed_by,
            "redeemed_at": item.redeemed_at.isoformat() if item.redeemed_at else None,
            "expires_at": item.expires_at.isoformat() if item.expires_at else None,
            "note": item.note or "",
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        if code:
            data["code"] = code
        return data

    @staticmethod
    def _public_record(item: RedeemRecordModel, code: RedeemCodeModel | None = None) -> dict[str, Any]:
        return {
            "id": item.id,
            "code_id": item.code_id,
            "code_preview": code.code_preview if code else "",
            "user_id": item.user_id,
            "quota_amount": int(item.quota_amount or 0),
            "balance_after": int(item.balance_after or 0),
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }

    def generate_codes(
        self,
        *,
        quota_amount: int,
        count: int,
        created_by: str = "",
        note: str = "",
        expires_at: str | None = None,
    ) -> list[dict[str, Any]]:
        amount = int(quota_amount or 0)
        if amount <= 0:
            raise ValueError("兑换额度必须大于 0")
        total = max(1, min(500, int(count or 1)))
        expires = _parse_expires_at(expires_at)
        now = _now()
        session = SessionLocal()
        try:
            items: list[tuple[RedeemCodeModel, str]] = []
            used_hashes: set[str] = set()
            while len(items) < total:
                code = _generate_code()
                code_hash = _hash_code(code)
                if code_hash in used_hashes:
                    continue
                used_hashes.add(code_hash)
                if session.query(RedeemCodeModel).filter(RedeemCodeModel.code_hash == code_hash).first() is not None:
                    continue
                item = RedeemCodeModel(
                    id=_new_id(),
                    code_hash=code_hash,
                    code_preview=_preview_code(code),
                    quota_amount=amount,
                    status="active",
                    created_by=str(created_by or "").strip() or None,
                    expires_at=expires,
                    note=str(note or "").strip(),
                    created_at=now,
                    updated_at=now,
                )
                session.add(item)
                items.append((item, code))
            session.commit()
            for item, _ in items:
                session.refresh(item)
            return [self._public_code(item, code=code) for item, code in items]
        finally:
            session.close()

    def list_codes(self, limit: int = 200) -> list[dict[str, Any]]:
        session = SessionLocal()
        try:
            rows = (
                session.query(RedeemCodeModel)
                .filter(RedeemCodeModel.deleted_at.is_(None))
                .order_by(RedeemCodeModel.created_at.desc())
                .limit(max(1, min(1000, int(limit or 200))))
                .all()
            )
            return [self._public_code(row) for row in rows]
        finally:
            session.close()

    def disable_code(self, code_id: str) -> dict[str, Any] | None:
        session = SessionLocal()
        try:
            item = session.query(RedeemCodeModel).filter(RedeemCodeModel.id == code_id, RedeemCodeModel.deleted_at.is_(None)).first()
            if item is None:
                return None
            if item.status == "active":
                item.status = "disabled"
                item.updated_at = _now()
                session.commit()
                session.refresh(item)
            return self._public_code(item)
        finally:
            session.close()

    def delete_code(self, code_id: str) -> bool:
        session = SessionLocal()
        try:
            item = session.query(RedeemCodeModel).filter(RedeemCodeModel.id == code_id, RedeemCodeModel.deleted_at.is_(None)).first()
            if item is None:
                return False
            item.deleted_at = _now()
            item.updated_at = item.deleted_at
            session.commit()
            return True
        finally:
            session.close()

    def redeem(self, user_id: str, code: str) -> dict[str, Any]:
        normalized = _normalize_code(code)
        if not normalized:
            raise ValueError("请输入兑换码")
        now = _now()
        session = SessionLocal()
        try:
            item = (
                session.query(RedeemCodeModel)
                .filter(RedeemCodeModel.code_hash == _hash_code(normalized), RedeemCodeModel.deleted_at.is_(None))
                .with_for_update()
                .first()
            )
            if item is None:
                raise ValueError("兑换码无效")
            if item.status == "disabled":
                raise ValueError("兑换码已禁用")
            if item.status == "used":
                raise ValueError("兑换码已使用")
            expires_at = _as_aware(item.expires_at)
            if expires_at is not None and expires_at < now:
                raise ValueError("兑换码已过期")
            user = session.query(UserModel).filter(UserModel.id == str(user_id or "").strip()).with_for_update().first()
            if user is None or user.status != "active":
                raise ValueError("用户不存在或已禁用")

            amount = int(item.quota_amount or 0)
            next_quota = int(user.image_quota or 0) + amount
            user.image_quota = next_quota
            user.updated_at = now
            item.status = "used"
            item.redeemed_by = user.id
            item.redeemed_at = now
            item.updated_at = now
            record = RedeemRecordModel(
                id=_new_id(),
                code_id=item.id,
                user_id=user.id,
                quota_amount=amount,
                balance_after=next_quota,
                created_at=now,
            )
            quota_record = QuotaRecordModel(
                id=_new_id(),
                user_id=user.id,
                delta=amount,
                reason="redeem_code",
                balance_after=next_quota,
                created_by=None,
                note=f"兑换码 {item.code_preview}",
                created_at=now,
            )
            session.add(record)
            session.add(quota_record)
            session.commit()
            session.refresh(user)
            session.refresh(item)
            session.refresh(record)
            user_service._identity_cache.clear()
            return {
                "user": _public_user(user),
                "code": self._public_code(item),
                "record": self._public_record(record, item),
            }
        finally:
            session.close()

    def list_user_records(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        session = SessionLocal()
        try:
            rows = (
                session.query(RedeemRecordModel, RedeemCodeModel)
                .join(RedeemCodeModel, RedeemCodeModel.id == RedeemRecordModel.code_id)
                .filter(RedeemRecordModel.user_id == str(user_id or "").strip())
                .order_by(RedeemRecordModel.created_at.desc())
                .limit(max(1, min(500, int(limit or 100))))
                .all()
            )
            return [self._public_record(record, code) for record, code in rows]
        finally:
            session.close()


redeem_code_service = RedeemCodeService()
