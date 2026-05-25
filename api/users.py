from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.support import require_admin, require_identity
from services.user_service import user_service


class PasswordLoginRequest(BaseModel):
    username: str = ""
    password: str = ""


class RegisterRequest(PasswordLoginRequest):
    pass


class UserStatusRequest(BaseModel):
    status: str


class QuotaGrantRequest(BaseModel):
    amount: int = Field(..., gt=0)
    note: str = ""


class APIKeyCreateRequest(BaseModel):
    name: str = ""


class APIKeyUpdateRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/auth/register")
    async def register(body: RegisterRequest):
        try:
            user = await run_in_threadpool(user_service.create_user, body.username, body.password)
            data = await run_in_threadpool(user_service.login, body.username, body.password)
            return {"ok": True, "user": user, "token": data["token"]}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/auth/password-login")
    async def password_login(body: PasswordLoginRequest):
        try:
            data = await run_in_threadpool(user_service.login, body.username, body.password)
            return {"ok": True, **data}
        except ValueError as exc:
            raise HTTPException(status_code=401, detail={"error": str(exc)}) from exc

    @router.get("/api/me")
    async def get_me(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        return {"user": identity}

    @router.get("/api/me/quota-records")
    async def get_my_quota_records(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") == "admin":
            return {"items": []}
        return {"items": await run_in_threadpool(user_service.list_quota_records, str(identity.get("id") or ""))}

    @router.get("/api/me/api-keys")
    async def list_my_api_keys(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") == "admin":
            return {"items": []}
        return {"items": await run_in_threadpool(user_service.list_api_keys, str(identity.get("id") or ""))}

    @router.post("/api/me/api-keys")
    async def create_my_api_key(body: APIKeyCreateRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") == "admin":
            raise HTTPException(status_code=400, detail={"error": "管理员请继续使用系统管理密钥"})
        try:
            item, raw_key = await run_in_threadpool(user_service.create_api_key, str(identity.get("id") or ""), body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "key": raw_key, "items": await run_in_threadpool(user_service.list_api_keys, str(identity.get("id") or ""))}

    @router.post("/api/me/api-keys/{key_id}")
    async def update_my_api_key(key_id: str, body: APIKeyUpdateRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        item = await run_in_threadpool(
            user_service.update_api_key,
            str(identity.get("id") or ""),
            key_id,
            body.model_dump(exclude_none=True),
        )
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "API Key 不存在"})
        return {"item": item, "items": await run_in_threadpool(user_service.list_api_keys, str(identity.get("id") or ""))}

    @router.delete("/api/me/api-keys/{key_id}")
    async def delete_my_api_key(key_id: str, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if not await run_in_threadpool(user_service.delete_api_key, str(identity.get("id") or ""), key_id):
            raise HTTPException(status_code=404, detail={"error": "API Key 不存在"})
        return {"items": await run_in_threadpool(user_service.list_api_keys, str(identity.get("id") or ""))}

    @router.get("/api/admin/users")
    async def list_users(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": await run_in_threadpool(user_service.list_users)}

    @router.post("/api/admin/users/{user_id}/status")
    async def set_user_status(user_id: str, body: UserStatusRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if body.status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail={"error": "status must be active or disabled"})
        item = await run_in_threadpool(user_service.set_user_status, user_id, body.status)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "用户不存在"})
        return {"item": item}

    @router.post("/api/admin/users/{user_id}/quota")
    async def grant_user_quota(user_id: str, body: QuotaGrantRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        try:
            result = await run_in_threadpool(
                user_service.grant_quota,
                user_id,
                body.amount,
                created_by=str(admin.get("id") or ""),
                note=body.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return result

    @router.get("/api/admin/users/{user_id}/quota-records")
    async def list_user_quota_records(user_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": await run_in_threadpool(user_service.list_quota_records, user_id)}

    return router
