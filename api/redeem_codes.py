from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.support import require_admin, require_identity
from services.redeem_code_service import redeem_code_service


class RedeemCodeGenerateRequest(BaseModel):
    quota_amount: int = Field(..., gt=0)
    count: int = Field(default=1, ge=1, le=500)
    expires_at: str = ""
    note: str = ""


class RedeemCodeConsumeRequest(BaseModel):
    code: str = ""


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/admin/redeem-codes")
    async def list_redeem_codes(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": await run_in_threadpool(redeem_code_service.list_codes)}

    @router.post("/api/admin/redeem-codes")
    async def generate_redeem_codes(body: RedeemCodeGenerateRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        try:
            items = await run_in_threadpool(
                redeem_code_service.generate_codes,
                quota_amount=body.quota_amount,
                count=body.count,
                created_by=str(admin.get("id") or ""),
                note=body.note,
                expires_at=body.expires_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"items": items}

    @router.post("/api/admin/redeem-codes/{code_id}/disable")
    async def disable_redeem_code(code_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        item = await run_in_threadpool(redeem_code_service.disable_code, code_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "兑换码不存在"})
        return {"item": item}

    @router.delete("/api/admin/redeem-codes/{code_id}")
    async def delete_redeem_code(code_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not await run_in_threadpool(redeem_code_service.delete_code, code_id):
            raise HTTPException(status_code=404, detail={"error": "兑换码不存在"})
        return {"ok": True}

    @router.post("/api/me/redeem-code")
    async def redeem_my_code(body: RedeemCodeConsumeRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") == "admin":
            raise HTTPException(status_code=400, detail={"error": "管理员账号不需要兑换额度"})
        try:
            return await run_in_threadpool(redeem_code_service.redeem, str(identity.get("id") or ""), body.code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/me/redeem-records")
    async def list_my_redeem_records(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") == "admin":
            return {"items": []}
        return {"items": await run_in_threadpool(redeem_code_service.list_user_records, str(identity.get("id") or ""))}

    return router
