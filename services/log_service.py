from __future__ import annotations

import hashlib
import json
import itertools
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse
from uuid import uuid4

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import Column, DateTime, String, Text

from services.app_database import Base, SessionLocal, init_app_database
from services.config import DATA_DIR
from services.protocol.error_response import anthropic_error_response, openai_error_response
from services.user_service import create_asset_access_token
from utils.helper import anthropic_sse_stream, sse_json_stream

LOG_TYPE_CALL = "call"
LOG_TYPE_ACCOUNT = "account"


class OperationLogModel(Base):
    __tablename__ = "operation_logs"

    id = Column(String(32), primary_key=True)
    time = Column(String(19), nullable=False, index=True)
    type = Column(String(32), nullable=False, index=True)
    summary = Column(String(512), nullable=False, default="")
    detail = Column(Text, nullable=False, default="{}")
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)


class LogService:
    def __init__(self, path: Path):
        self.path = path
        init_app_database()
        self._migrate_legacy_file()

    def _migrate_legacy_file(self) -> None:
        if not self.path.exists():
            return
        session = SessionLocal()
        try:
            if session.query(OperationLogModel).count() > 0:
                return
            rows: list[OperationLogModel] = []
            for line_number, raw_line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
                item = self._parse_line(raw_line, line_number)
                if item is None:
                    continue
                rows.append(
                    OperationLogModel(
                        id=str(item.get("id") or uuid4().hex)[:32],
                        time=str(item.get("time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))[:19],
                        type=str(item.get("type") or ""),
                        summary=str(item.get("summary") or ""),
                        detail=json.dumps(item.get("detail") or {}, ensure_ascii=False, separators=(",", ":")),
                    )
                )
            if rows:
                session.add_all(rows)
                session.commit()
        finally:
            session.close()

    @staticmethod
    def _legacy_id(raw_line: str, line_number: int) -> str:
        payload = f"{line_number}:{raw_line}".encode("utf-8", errors="ignore")
        return hashlib.sha1(payload).hexdigest()[:24]

    def _parse_line(self, raw_line: str, line_number: int) -> dict[str, Any] | None:
        try:
            item = json.loads(raw_line)
        except Exception:
            return None
        if not isinstance(item, dict):
            return None
        parsed = dict(item)
        parsed["id"] = str(parsed.get("id") or self._legacy_id(raw_line, line_number))
        return parsed

    @staticmethod
    def _serialize_item(item: dict[str, Any]) -> str:
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _matches_filters(item: dict[str, Any], *, type: str = "", start_date: str = "", end_date: str = "") -> bool:
        t = str(item.get("time") or "")
        day = t[:10]
        if type and item.get("type") != type:
            return False
        if start_date and day < start_date:
            return False
        if end_date and day > end_date:
            return False
        return True

    def add(self, type: str, summary: str = "", detail: dict[str, Any] | None = None, **data: Any) -> None:
        session = SessionLocal()
        try:
            session.add(
                OperationLogModel(
                    id=uuid4().hex,
                    time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    type=str(type or "").strip(),
                    summary=str(summary or ""),
                    detail=json.dumps(detail or data, ensure_ascii=False, separators=(",", ":")),
                )
            )
            session.commit()
        finally:
            session.close()

    def list(self, type: str = "", start_date: str = "", end_date: str = "", limit: int = 200, owner_id: str = "") -> list[dict[str, Any]]:
        owner_filter = str(owner_id or "").strip()
        session = SessionLocal()
        try:
            query = session.query(OperationLogModel).filter(OperationLogModel.deleted_at.is_(None))
            if type:
                query = query.filter(OperationLogModel.type == type)
            if owner_filter:
                query = query.filter(OperationLogModel.detail.contains(f'"key_id":"{owner_filter}"'))
            if start_date:
                query = query.filter(OperationLogModel.time >= f"{start_date} 00:00:00")
            if end_date:
                query = query.filter(OperationLogModel.time <= f"{end_date} 23:59:59")
            rows = query.order_by(OperationLogModel.time.desc()).limit(max(1, min(1000, int(limit or 200)))).all()
            items: list[dict[str, Any]] = []
            for row in rows:
                try:
                    detail = json.loads(str(row.detail or "{}"))
                except Exception:
                    detail = {}
                if isinstance(detail, dict):
                    detail = _signed_detail_image_urls(detail, str(detail.get("key_id") or "admin"))
                items.append({
                    "id": row.id,
                    "time": row.time,
                    "type": row.type,
                    "summary": row.summary,
                    "detail": detail if isinstance(detail, dict) else {},
                })
            return items
        finally:
            session.close()

    def delete(self, ids: list[str], owner_id: str = "") -> dict[str, int]:
        target_ids = {str(item or "").strip() for item in ids if str(item or "").strip()}
        if not target_ids:
            return {"removed": 0}
        owner_filter = str(owner_id or "").strip()
        session = SessionLocal()
        try:
            query = session.query(OperationLogModel).filter(OperationLogModel.id.in_(target_ids), OperationLogModel.deleted_at.is_(None))
            if owner_filter:
                query = query.filter(OperationLogModel.detail.contains(f'"key_id":"{owner_filter}"'))
            rows = query.all()
            now = datetime.now()
            for row in rows:
                row.deleted_at = now
            session.commit()
            return {"removed": len(rows)}
        finally:
            session.close()


log_service = LogService(DATA_DIR / "logs.jsonl")


def _collect_urls(value: object) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "url" and isinstance(item, str):
                urls.append(item)
            elif key == "urls" and isinstance(item, list):
                urls.extend(str(url) for url in item if isinstance(url, str))
            else:
                urls.extend(_collect_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_collect_urls(item))
    return urls


def _request_excerpt(text: object, limit: int = 1000) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _signed_internal_image_url(url: str, owner_id: str) -> str:
    value = str(url or "").strip()
    if not value or "token=" in value:
        return value
    parsed = urlparse(value)
    marker = "/images/"
    marker_index = str(parsed.path or "").find(marker)
    if marker_index < 0:
        return value
    rel = unquote(str(parsed.path or "")[marker_index + len(marker):]).lstrip("/")
    if not rel:
        return value
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["token"] = create_asset_access_token(owner_id=owner_id or "admin", rel=rel)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _signed_detail_image_urls(value: object, owner_id: str) -> object:
    if isinstance(value, dict):
        signed: dict[str, object] = {}
        for key, item in value.items():
            if key == "url" and isinstance(item, str):
                signed[key] = _signed_internal_image_url(item, owner_id)
            elif key == "urls" and isinstance(item, list):
                signed[key] = [_signed_internal_image_url(url, owner_id) if isinstance(url, str) else url for url in item]
            else:
                signed[key] = _signed_detail_image_urls(item, owner_id)
        return signed
    if isinstance(value, list):
        return [_signed_detail_image_urls(item, owner_id) for item in value]
    return value


def _image_error_response(exc: Exception) -> JSONResponse:
    message = str(exc)
    if "no available image quota" in message.lower():
        return openai_error_response(
            {
                "error": {
                    "message": "no available image quota",
                    "type": "insufficient_quota",
                    "param": None,
                    "code": "insufficient_quota",
                }
            },
            429,
        )
    if hasattr(exc, "to_openai_error") and hasattr(exc, "status_code"):
        return JSONResponse(status_code=int(exc.status_code), content=exc.to_openai_error())
    return openai_error_response(message, 502)


def _protocol_error_response(exc: Exception, status_code: int, sse: str) -> JSONResponse:
    message = str(exc)
    if sse == "anthropic":
        return anthropic_error_response(message, status_code)
    return openai_error_response(message, status_code)


def _next_item(items):
    try:
        return True, next(items)
    except StopIteration:
        return False, None


@dataclass
class LoggedCall:
    identity: dict[str, object]
    endpoint: str
    model: str
    summary: str
    started: float = field(default_factory=time.time)
    request_text: str = ""

    async def run(self, handler, *args, sse: str = "openai"):
        from services.protocol.conversation import ImageGenerationError

        try:
            result = await run_in_threadpool(handler, *args)
        except ImageGenerationError as exc:
            self.log("调用失败", status="failed", error=str(exc))
            return _image_error_response(exc)
        except HTTPException as exc:
            self.log("调用失败", status="failed", error=str(exc.detail))
            raise
        except Exception as exc:
            self.log("调用失败", status="failed", error=str(exc))
            return _protocol_error_response(exc, 502, sse)

        if isinstance(result, dict):
            self.log("调用完成", result)
            return result

        sender = anthropic_sse_stream if sse == "anthropic" else sse_json_stream
        try:
            has_first, first = await run_in_threadpool(_next_item, result)
        except ImageGenerationError as exc:
            self.log("调用失败", status="failed", error=str(exc))
            return _image_error_response(exc)
        except HTTPException as exc:
            self.log("调用失败", status="failed", error=str(exc.detail))
            raise
        except Exception as exc:
            self.log("调用失败", status="failed", error=str(exc))
            return _protocol_error_response(exc, 502, sse)
        if not has_first:
            self.log("流式调用结束")
            return StreamingResponse(sender(()), media_type="text/event-stream")
        return StreamingResponse(sender(self.stream(itertools.chain([first], result))), media_type="text/event-stream")

    def stream(self, items):
        urls: list[str] = []
        failed = False
        try:
            for item in items:
                urls.extend(_collect_urls(item))
                yield item
        except Exception as exc:
            failed = True
            self.log("流式调用失败", status="failed", error=str(exc), urls=urls)
            raise
        finally:
            if not failed:
                self.log("流式调用结束", urls=urls)

    def log(self, suffix: str, result: object = None, status: str = "success", error: str = "",
            urls: list[str] | None = None) -> None:
        detail = {
            "key_id": self.identity.get("id"),
            "key_name": self.identity.get("name"),
            "role": self.identity.get("role"),
            "endpoint": self.endpoint,
            "model": self.model,
            "started_at": datetime.fromtimestamp(self.started).strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration_ms": int((time.time() - self.started) * 1000),
            "status": status,
        }
        request_excerpt = _request_excerpt(self.request_text)
        if request_excerpt:
            detail["request_text"] = request_excerpt
        if error:
            detail["error"] = error
        collected_urls = [*(urls or []), *_collect_urls(result)]
        if collected_urls:
            detail["urls"] = list(dict.fromkeys(collected_urls))
        log_service.add(LOG_TYPE_CALL, f"{self.summary}{suffix}", detail)
