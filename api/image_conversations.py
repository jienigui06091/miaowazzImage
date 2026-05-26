from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict

from api.support import require_identity
from services.image_conversation_service import image_conversation_service


class ImageConversationPayload(BaseModel):
    model_config = ConfigDict(extra="allow")


class ImageConversationBulkRequest(BaseModel):
    items: list[dict[str, Any]] = []


def _owner_id(identity: dict[str, object]) -> str:
    owner = str(identity.get("id") or "").strip()
    if not owner:
        raise HTTPException(status_code=401, detail={"error": "invalid identity"})
    return owner


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/image-conversations")
    async def list_image_conversations(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        items = await run_in_threadpool(image_conversation_service.list, _owner_id(identity))
        return {"items": items}

    @router.post("/api/image-conversations")
    async def save_image_conversation(body: ImageConversationPayload, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        try:
            item = await run_in_threadpool(image_conversation_service.save, _owner_id(identity), body.model_dump(mode="python"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item}

    @router.post("/api/image-conversations/bulk")
    async def save_image_conversations(body: ImageConversationBulkRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        try:
            items = await run_in_threadpool(image_conversation_service.save_many, _owner_id(identity), body.items)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"items": items}

    @router.delete("/api/image-conversations/{conversation_id}")
    async def delete_image_conversation(conversation_id: str, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        removed = await run_in_threadpool(image_conversation_service.delete, _owner_id(identity), conversation_id)
        return {"removed": 1 if removed else 0}

    @router.post("/api/image-conversations/clear")
    async def clear_image_conversations(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        removed = await run_in_threadpool(image_conversation_service.clear, _owner_id(identity))
        return {"removed": removed}

    return router
