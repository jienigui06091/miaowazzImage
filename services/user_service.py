from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Session

from services.app_database import Base, SessionLocal, init_app_database
from services.config import config

UserRole = Literal["admin", "user"]
UserStatus = Literal["active", "disabled"]

TOKEN_TTL_SECONDS = int(os.getenv("APP_ACCESS_TOKEN_TTL_SECONDS", "604800") or "604800")
JWT_SECRET = os.getenv("APP_JWT_SECRET", "").strip() or config.auth_key
PASSWORD_ITERATIONS = 260_000


class UserModel(Base):
    __tablename__ = "operation_users"

    id = Column(String(32), primary_key=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    password_hash = Column(String(512), nullable=False)
    role = Column(String(16), nullable=False, default="user")
    status = Column(String(16), nullable=False, default="active")
    image_quota = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class UserAPIKeyModel(Base):
    __tablename__ = "operation_api_keys"

    id = Column(String(32), primary_key=True)
    user_id = Column(String(32), ForeignKey("operation_users.id"), nullable=False, index=True)
    key_hash = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False, default="API Key")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)


class QuotaRecordModel(Base):
    __tablename__ = "operation_quota_records"

    id = Column(String(32), primary_key=True)
    user_id = Column(String(32), ForeignKey("operation_users.id"), nullable=False, index=True)
    delta = Column(Integer, nullable=False)
    reason = Column(String(64), nullable=False)
    balance_after = Column(Integer, nullable=False)
    created_by = Column(String(32), nullable=True)
    note = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False)


class GeneratedAssetModel(Base):
    __tablename__ = "operation_generated_assets"

    id = Column(String(32), primary_key=True)
    user_id = Column(String(32), ForeignKey("operation_users.id"), nullable=False, index=True)
    task_id = Column(String(120), nullable=True, index=True)
    r2_object_key = Column(String(1024), nullable=False)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(120), nullable=False, default="image/png")
    size = Column(Integer, nullable=False, default=0)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "r2_object_key", name="uq_generated_asset_owner_key"),)


class UserAccountBindingModel(Base):
    __tablename__ = "operation_user_account_bindings"

    id = Column(String(32), primary_key=True)
    user_id = Column(String(32), ForeignKey("operation_users.id"), nullable=False, index=True)
    account_hash = Column(String(128), nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "account_hash", name="uq_user_account_binding"),)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


def _b64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _json_dumps(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def hash_account_token(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_urlsafe(18)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${base64.b64encode(digest).decode('ascii')}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, digest = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(base64.b64decode(digest.encode("ascii")), candidate)
    except Exception:
        return False


def create_access_token(user: UserModel) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }
    signing_input = f"{_b64url_encode(_json_dumps(header))}.{_b64url_encode(_json_dumps(payload))}"
    signature = hmac.new(JWT_SECRET.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def create_asset_access_token(*, owner_id: str, rel: str, ttl_seconds: int = 2592000) -> str:
    now = int(time.time())
    payload = {
        "typ": "asset",
        "sub": owner_id,
        "rel": rel,
        "iat": now,
        "exp": now + max(60, int(ttl_seconds or 3600)),
    }
    signing_input = _b64url_encode(_json_dumps(payload))
    signature = hmac.new(JWT_SECRET.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def verify_asset_access_token(token: str, rel: str) -> dict[str, Any] | None:
    try:
        payload_part, signature = str(token or "").rsplit(".", 1)
        expected = hmac.new(JWT_SECRET.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(signature), expected):
            return None
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("typ") != "asset":
            return None
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        if str(payload.get("rel") or "") != rel:
            return None
        return payload
    except Exception:
        return None


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        header_payload, signature = token.rsplit(".", 1)
        expected = hmac.new(JWT_SECRET.encode("utf-8"), header_payload.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(signature), expected):
            return None
        _, payload_part = header_payload.split(".", 1)
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _clean_username(username: str) -> str:
    return str(username or "").strip().lower()


def _validate_password(password: str) -> str:
    value = str(password or "")
    if len(value) < 8:
        raise ValueError("密码至少需要 8 个字符")
    return value


def _public_user(user: UserModel) -> dict[str, Any]:
    assigned_count = 0
    try:
        from services.account_service import account_service

        known_hashes = account_service.list_account_hashes()
        session = SessionLocal()
        try:
            assigned_count = len({
                str(row[0] or "").strip()
                for row in session.query(UserAccountBindingModel.account_hash)
                .filter(UserAccountBindingModel.user_id == user.id, UserAccountBindingModel.enabled.is_(True))
                .all()
                if str(row[0] or "").strip() in known_hashes
            })
        finally:
            session.close()
    except Exception:
        assigned_count = 0
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "status": user.status,
        "image_quota": int(user.image_quota or 0),
        "assigned_account_count": int(assigned_count),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def _identity_from_user(user: UserModel) -> dict[str, Any]:
    return {
        "id": user.id,
        "name": user.username,
        "username": user.username,
        "role": user.role,
        "status": user.status,
        "image_quota": int(user.image_quota or 0),
        "auth_type": "user",
    }


class UserService:
    def __init__(self):
        self._identity_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        init_app_database()
        self.ensure_default_admin()

    def _session(self) -> Session:
        return SessionLocal()

    def create_user(self, username: str, password: str, *, role: UserRole = "user", initial_quota: int = 0) -> dict[str, Any]:
        normalized_username = _clean_username(username)
        if len(normalized_username) < 3:
            raise ValueError("用户名至少需要 3 个字符")
        if len(str(password or "")) < 8:
            raise ValueError("密码至少需要 8 个字符")
        if role not in {"admin", "user"}:
            role = "user"
        now = _now()
        session = self._session()
        try:
            if session.query(UserModel).filter(UserModel.username == normalized_username).first():
                raise ValueError("用户名已存在")
            user = UserModel(
                id=_new_id(),
                username=normalized_username,
                password_hash=hash_password(password),
                role=role,
                status="active",
                image_quota=max(0, int(initial_quota or 0)),
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return _public_user(user)
        finally:
            session.close()

    def ensure_default_admin(self) -> None:
        username = _clean_username(os.getenv("APP_ADMIN_USERNAME", "admin"))
        password = os.getenv("APP_ADMIN_PASSWORD", "").strip() or str(config.auth_key or "").strip()
        if not username or len(str(password or "")) < 8:
            return
        now = _now()
        session = self._session()
        try:
            if session.query(UserModel).filter(UserModel.role == "admin").first() is not None:
                return
            user = session.query(UserModel).filter(UserModel.username == username).first()
            if user is not None:
                user.role = "admin"
                user.status = "active"
                user.updated_at = now
            else:
                user = UserModel(
                    id=_new_id(),
                    username=username,
                    password_hash=hash_password(password),
                    role="admin",
                    status="active",
                    image_quota=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(user)
            session.commit()
        finally:
            session.close()

    def login(self, username: str, password: str) -> dict[str, Any]:
        normalized_username = _clean_username(username)
        session = self._session()
        try:
            user = session.query(UserModel).filter(UserModel.username == normalized_username).first()
            if user is None or user.status != "active" or not verify_password(password, str(user.password_hash or "")):
                raise ValueError("用户名或密码错误")
            return {"token": create_access_token(user), "user": _public_user(user)}
        finally:
            session.close()

    def change_password(self, user_id: str, current_password: str, new_password: str) -> dict[str, Any]:
        next_password = _validate_password(new_password)
        session = self._session()
        try:
            user = session.query(UserModel).filter(UserModel.id == user_id).first()
            if user is None or user.status != "active":
                raise ValueError("用户不存在或已禁用")
            if not verify_password(str(current_password or ""), str(user.password_hash or "")):
                raise ValueError("当前密码不正确")
            user.password_hash = hash_password(next_password)
            user.updated_at = _now()
            session.commit()
            session.refresh(user)
            self._identity_cache.clear()
            return _public_user(user)
        finally:
            session.close()

    def reset_password(self, user_id: str, new_password: str) -> dict[str, Any] | None:
        next_password = _validate_password(new_password)
        session = self._session()
        try:
            user = session.query(UserModel).filter(UserModel.id == user_id).first()
            if user is None:
                return None
            user.password_hash = hash_password(next_password)
            user.updated_at = _now()
            session.commit()
            session.refresh(user)
            self._identity_cache.clear()
            return _public_user(user)
        finally:
            session.close()

    def authenticate_token(self, token: str) -> dict[str, Any] | None:
        payload = decode_access_token(token)
        if not payload:
            return None
        user_id = str(payload.get("sub") or "").strip()
        if not user_id:
            return None
        return self.get_identity(user_id)

    def authenticate_api_key(self, raw_key: str) -> dict[str, Any] | None:
        key_hash = _hash_api_key(raw_key)
        session = self._session()
        try:
            api_key = session.query(UserAPIKeyModel).filter(UserAPIKeyModel.key_hash == key_hash, UserAPIKeyModel.enabled.is_(True)).first()
            if api_key is None:
                return None
            user = session.query(UserModel).filter(UserModel.id == api_key.user_id).first()
            if user is None or user.status != "active":
                return None
            api_key.last_used_at = _now()
            session.commit()
            identity = _identity_from_user(user)
            identity["api_key_id"] = api_key.id
            identity["auth_type"] = "api_key"
            return identity
        finally:
            session.close()

    def authenticate_bearer(self, token: str) -> dict[str, Any] | None:
        cache_key = str(token or "").strip()
        if cache_key:
            cached = self._identity_cache.get(cache_key)
            if cached and cached[0] > time.time():
                return dict(cached[1])
        if token.startswith("sk-user-"):
            identity = self.authenticate_api_key(token)
        else:
            identity = self.authenticate_token(token)
        if cache_key and identity is not None:
            self._identity_cache[cache_key] = (time.time() + 30, dict(identity))
        return identity

    def get_identity(self, user_id: str) -> dict[str, Any] | None:
        session = self._session()
        try:
            user = session.query(UserModel).filter(UserModel.id == user_id).first()
            if user is None or user.status != "active":
                return None
            return _identity_from_user(user)
        finally:
            session.close()

    def list_users(self) -> list[dict[str, Any]]:
        session = self._session()
        try:
            users = session.query(UserModel).order_by(UserModel.created_at.desc()).all()
            return [_public_user(user) for user in users]
        finally:
            session.close()

    def set_user_status(self, user_id: str, status: UserStatus) -> dict[str, Any] | None:
        session = self._session()
        try:
            user = session.query(UserModel).filter(UserModel.id == user_id).first()
            if user is None:
                return None
            user.status = "active" if status == "active" else "disabled"
            user.updated_at = _now()
            session.commit()
            session.refresh(user)
            self._identity_cache.clear()
            return _public_user(user)
        finally:
            session.close()

    def grant_quota(self, user_id: str, amount: int, *, created_by: str = "", note: str = "") -> dict[str, Any]:
        if int(amount or 0) <= 0:
            raise ValueError("增加额度必须大于 0")
        if not self.user_has_assigned_accounts(user_id):
            raise ValueError("please assign at least one image account before granting quota")
        return self._change_quota(user_id, int(amount), reason="admin_grant", created_by=created_by, note=note)

    def reserve_quota(self, identity: dict[str, Any], amount: int, *, reason: str = "generate") -> dict[str, Any] | None:
        if identity.get("role") == "admin":
            return None
        user_id = str(identity.get("id") or "").strip()
        if not user_id:
            raise ValueError("用户身份无效")
        if not self.user_has_assigned_accounts(user_id):
            raise ValueError("no assigned image account")
        if int(amount or 0) <= 0:
            return None
        return self._change_quota(user_id, -int(amount), reason=reason, created_by=user_id)

    def refund_quota(self, user_id: str, amount: int, *, reason: str = "refund") -> dict[str, Any] | None:
        if int(amount or 0) <= 0:
            return None
        return self._change_quota(user_id, int(amount), reason=reason, created_by="system")

    def _change_quota(self, user_id: str, delta: int, *, reason: str, created_by: str = "", note: str = "") -> dict[str, Any]:
        session = self._session()
        try:
            query = session.query(UserModel).filter(UserModel.id == user_id)
            user = query.with_for_update().first()
            if user is None:
                raise ValueError("用户不存在")
            if user.status != "active":
                raise ValueError("用户已禁用")
            next_quota = int(user.image_quota or 0) + int(delta)
            if next_quota < 0:
                raise ValueError("生成额度不足")
            user.image_quota = next_quota
            user.updated_at = _now()
            record = QuotaRecordModel(
                id=_new_id(),
                user_id=user.id,
                delta=int(delta),
                reason=reason,
                balance_after=next_quota,
                created_by=created_by or None,
                note=note or "",
                created_at=_now(),
            )
            session.add(record)
            session.commit()
            session.refresh(user)
            return {"user": _public_user(user), "record": self._public_quota_record(record)}
        finally:
            session.close()

    def record_generated_asset(
        self,
        *,
        user_id: str,
        rel: str,
        task_id: str = "",
        filename: str = "",
        content_type: str = "image/png",
        size: int = 0,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any] | None:
        owner = str(user_id or "").strip()
        object_key = str(rel or "").strip().replace("\\", "/").lstrip("/")
        if not owner or not object_key:
            return None
        session = self._session()
        try:
            existing = (
                session.query(GeneratedAssetModel)
                .filter(GeneratedAssetModel.user_id == owner, GeneratedAssetModel.r2_object_key == object_key)
                .first()
            )
            if existing is not None:
                return self._public_asset(existing)
            item = GeneratedAssetModel(
                id=_new_id(),
                user_id=owner,
                task_id=str(task_id or "").strip() or None,
                r2_object_key=object_key,
                filename=filename or object_key.rsplit("/", 1)[-1] or "image.png",
                content_type=content_type or "image/png",
                size=max(0, int(size or 0)),
                width=width,
                height=height,
                created_at=_now(),
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            return self._public_asset(item)
        finally:
            session.close()

    def get_asset_by_rel(self, rel: str) -> dict[str, Any] | None:
        object_key = str(rel or "").strip().replace("\\", "/").lstrip("/")
        if not object_key:
            return None
        session = self._session()
        try:
            item = session.query(GeneratedAssetModel).filter(GeneratedAssetModel.r2_object_key == object_key).first()
            return self._public_asset(item) if item is not None else None
        finally:
            session.close()

    def can_access_asset(self, identity: dict[str, Any] | None, rel: str, token: str = "") -> bool:
        safe_rel = str(rel or "").strip().replace("\\", "/").lstrip("/")
        if token and verify_asset_access_token(token, safe_rel):
            return True
        asset = self.get_asset_by_rel(safe_rel)
        if asset is None:
            return bool(identity and identity.get("role") == "admin")
        if identity and identity.get("role") == "admin":
            return True
        return bool(identity and str(identity.get("id") or "") == str(asset.get("user_id") or ""))

    @staticmethod
    def _public_asset(item: GeneratedAssetModel) -> dict[str, Any]:
        return {
            "id": item.id,
            "user_id": item.user_id,
            "task_id": item.task_id,
            "r2_object_key": item.r2_object_key,
            "filename": item.filename,
            "content_type": item.content_type,
            "size": int(item.size or 0),
            "width": item.width,
            "height": item.height,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }

    @staticmethod
    def _public_quota_record(record: QuotaRecordModel) -> dict[str, Any]:
        return {
            "id": record.id,
            "user_id": record.user_id,
            "delta": int(record.delta or 0),
            "reason": record.reason,
            "balance_after": int(record.balance_after or 0),
            "created_by": record.created_by,
            "note": record.note,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    def list_quota_records(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        session = self._session()
        try:
            rows = (
                session.query(QuotaRecordModel)
                .filter(QuotaRecordModel.user_id == user_id)
                .order_by(QuotaRecordModel.created_at.desc())
                .limit(max(1, min(500, int(limit or 100))))
                .all()
            )
            return [self._public_quota_record(row) for row in rows]
        finally:
            session.close()

    def account_hashes_for_user(self, user_id: str) -> set[str]:
        owner = str(user_id or "").strip()
        if not owner:
            return set()
        session = self._session()
        try:
            rows = (
                session.query(UserAccountBindingModel.account_hash)
                .filter(UserAccountBindingModel.user_id == owner, UserAccountBindingModel.enabled.is_(True))
                .all()
            )
            hashes = {str(row[0] or "").strip() for row in rows if str(row[0] or "").strip()}
            try:
                from services.account_service import account_service

                return hashes & account_service.list_account_hashes()
            except Exception:
                return hashes
        finally:
            session.close()

    def user_has_assigned_accounts(self, user_id: str) -> bool:
        session = self._session()
        try:
            user = session.query(UserModel).filter(UserModel.id == str(user_id or "").strip()).first()
            if user is None:
                raise ValueError("user not found")
            if user.role == "admin":
                return True
            return bool(self.account_hashes_for_user(user.id))
        finally:
            session.close()

    def set_user_account_bindings(self, user_id: str, access_tokens: list[str], *, created_by: str = "") -> list[dict[str, Any]]:
        from services.account_service import account_service

        target_user_id = str(user_id or "").strip()
        token_hashes = {hash_account_token(token) for token in access_tokens if str(token or "").strip()}
        known_hashes = account_service.list_account_hashes()
        unknown_count = len(token_hashes - known_hashes)
        if unknown_count:
            raise ValueError(f"{unknown_count} account(s) are not in the account pool")
        now = _now()
        session = self._session()
        try:
            user = session.query(UserModel).filter(UserModel.id == target_user_id).first()
            if user is None:
                raise ValueError("user not found")
            if user.role == "admin":
                return []
            rows = session.query(UserAccountBindingModel).filter(UserAccountBindingModel.user_id == target_user_id).all()
            by_hash = {str(row.account_hash): row for row in rows}
            for account_hash, row in by_hash.items():
                row.enabled = account_hash in token_hashes
                row.updated_at = now
            for account_hash in token_hashes:
                if account_hash not in by_hash:
                    session.add(UserAccountBindingModel(
                        id=_new_id(),
                        user_id=target_user_id,
                        account_hash=account_hash,
                        enabled=True,
                        created_by=str(created_by or "").strip() or None,
                        created_at=now,
                        updated_at=now,
                    ))
            session.commit()
            return self.list_user_account_bindings(target_user_id)
        finally:
            session.close()

    def list_user_account_bindings(self, user_id: str) -> list[dict[str, Any]]:
        from services.account_service import account_service

        target_user_id = str(user_id or "").strip()
        account_map = {account_service.token_hash(str(item.get("access_token") or "")): item for item in account_service.list_accounts()}
        session = self._session()
        try:
            rows = (
                session.query(UserAccountBindingModel)
                .filter(UserAccountBindingModel.user_id == target_user_id, UserAccountBindingModel.enabled.is_(True))
                .order_by(UserAccountBindingModel.created_at.asc())
                .all()
            )
            result: list[dict[str, Any]] = []
            for row in rows:
                account = account_map.get(str(row.account_hash))
                result.append({
                    "id": row.id,
                    "user_id": row.user_id,
                    "account_hash": row.account_hash,
                    "account": self._public_bound_account(account) if account else None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                })
            return result
        finally:
            session.close()

    def create_api_key(self, user_id: str, name: str = "") -> tuple[dict[str, Any], str]:
        raw_key = f"sk-user-{secrets.token_urlsafe(32)}"
        now = _now()
        item = UserAPIKeyModel(
            id=_new_id(),
            user_id=user_id,
            key_hash=_hash_api_key(raw_key),
            name=str(name or "API Key").strip() or "API Key",
            enabled=True,
            created_at=now,
            last_used_at=None,
        )
        session = self._session()
        try:
            if session.query(UserModel).filter(UserModel.id == user_id, UserModel.status == "active").first() is None:
                raise ValueError("用户不存在或已禁用")
            session.add(item)
            session.commit()
            session.refresh(item)
            return self._public_api_key(item), raw_key
        finally:
            session.close()

    def list_api_keys(self, user_id: str) -> list[dict[str, Any]]:
        session = self._session()
        try:
            rows = session.query(UserAPIKeyModel).filter(UserAPIKeyModel.user_id == user_id).order_by(UserAPIKeyModel.created_at.desc()).all()
            return [self._public_api_key(row) for row in rows]
        finally:
            session.close()

    def update_api_key(self, user_id: str, key_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        session = self._session()
        try:
            row = session.query(UserAPIKeyModel).filter(UserAPIKeyModel.user_id == user_id, UserAPIKeyModel.id == key_id).first()
            if row is None:
                return None
            if "name" in updates and updates.get("name") is not None:
                row.name = str(updates.get("name") or "").strip() or row.name
            if "enabled" in updates and updates.get("enabled") is not None:
                row.enabled = bool(updates.get("enabled"))
            session.commit()
            session.refresh(row)
            return self._public_api_key(row)
        finally:
            session.close()

    def delete_api_key(self, user_id: str, key_id: str) -> bool:
        session = self._session()
        try:
            row = session.query(UserAPIKeyModel).filter(UserAPIKeyModel.user_id == user_id, UserAPIKeyModel.id == key_id).first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    @staticmethod
    def _public_api_key(row: UserAPIKeyModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "enabled": bool(row.enabled),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        }

    @staticmethod
    def _public_bound_account(account: dict[str, Any] | None) -> dict[str, Any] | None:
        if not account:
            return None
        return {
            "access_token": account.get("access_token"),
            "email": account.get("email"),
            "type": account.get("type"),
            "status": account.get("status"),
            "quota": int(account.get("quota") or 0),
            "image_quota_unknown": bool(account.get("image_quota_unknown")),
            "account_id": account.get("account_id"),
            "user_id": account.get("user_id"),
            "success": int(account.get("success") or 0),
            "fail": int(account.get("fail") or 0),
            "last_used_at": account.get("last_used_at"),
        }


user_service = UserService()
