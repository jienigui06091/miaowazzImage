from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from urllib.parse import quote, urlencode, urlparse

from curl_cffi import requests
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from services.app_database import Base, SessionLocal, init_app_database
from services.config import DATA_DIR, config
from services.user_service import create_asset_access_token, user_service

IMAGE_INDEX_FILE = DATA_DIR / "image_index.json"
IMAGE_INDEX_LOCK = Lock()
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class ImageStorageError(RuntimeError):
    pass


class ImageRecordModel(Base):
    __tablename__ = "operation_images"

    rel = Column(String(1024), primary_key=True)
    name = Column(String(255), nullable=False)
    date = Column(String(10), nullable=False, index=True)
    size = Column(Integer, nullable=False, default=0)
    created_at = Column(String(19), nullable=False, index=True)
    storage = Column(String(32), nullable=False, default="r2")
    local = Column(Boolean, nullable=False, default=False)
    webdav = Column(Boolean, nullable=False, default=False)
    r2 = Column(Boolean, nullable=False, default=False)
    remote_url = Column(String(2048), nullable=False, default="")
    owner_id = Column(String(32), nullable=False, default="", index=True)
    task_id = Column(String(120), nullable=False, default="", index=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)


@dataclass(frozen=True)
class StoredImage:
    rel: str
    url: str
    storage: str
    size: int


def _clean(value: object) -> str:
    return str(value or "").strip()


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_relative_path(path: str) -> str:
    value = str(path or "").strip().replace("\\", "/").lstrip("/")
    if not value:
        raise HTTPException(status_code=404, detail="image not found")
    parts = Path(value).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=404, detail="image not found")
    return Path(*parts).as_posix()


def _image_dimensions(payload: bytes) -> tuple[int, int] | None:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.size
    except Exception:
        return None


def _is_image_rel(path: str) -> bool:
    try:
        safe_rel = _safe_relative_path(path)
    except HTTPException:
        return False
    return Path(safe_rel).suffix.lower() in IMAGE_EXTENSIONS


def _local_image_path(relative_path: str) -> Path:
    rel = _safe_relative_path(relative_path)
    root = config.images_dir.resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="image not found") from exc
    return path


def _read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_object(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


class WebDAVClient:
    def __init__(self, settings: dict[str, object]):
        self.url = _clean(settings.get("webdav_url")).rstrip("/")
        self.username = _clean(settings.get("webdav_username"))
        self.password = _clean(settings.get("webdav_password"))
        self.root_path = _clean(settings.get("webdav_root_path")).strip("/")
        self.session = requests.Session()

    def _auth_kwargs(self) -> dict[str, object]:
        return {"auth": (self.username, self.password)} if self.username or self.password else {}

    def _request(self, method: str, url: str, **kwargs):
        response = self.session.request(method, url, timeout=30, **self._auth_kwargs(), **kwargs)
        if response.status_code >= 400 and not (method == "MKCOL" and response.status_code in {405}):
            raise ImageStorageError(f"WebDAV {method} failed: HTTP {response.status_code}")
        return response

    def remote_url(self, rel: str = "") -> str:
        parts = [part for part in [self.root_path, _safe_relative_path(rel) if rel else ""] if part]
        encoded = "/".join(quote(part, safe="") for item in parts for part in item.split("/") if part)
        return f"{self.url}/{encoded}" if encoded else self.url

    def ensure_dirs(self, rel: str) -> None:
        parts = [part for part in [self.root_path, Path(_safe_relative_path(rel)).parent.as_posix()] if part and part != "."]
        current = self.url
        for item in "/".join(parts).split("/"):
            if not item:
                continue
            current = f"{current}/{quote(item, safe='')}"
            response = self.session.request("MKCOL", current, timeout=30, **self._auth_kwargs())
            if response.status_code in {201, 405}:
                continue
            if response.status_code >= 400:
                raise ImageStorageError(f"WebDAV MKCOL failed: HTTP {response.status_code}")

    def put(self, rel: str, payload: bytes, content_type: str = "image/png") -> str:
        self.ensure_dirs(rel)
        url = self.remote_url(rel)
        self._request("PUT", url, data=payload, headers={"Content-Type": content_type})
        return url

    def get(self, rel: str) -> bytes:
        response = self._request("GET", self.remote_url(rel))
        return bytes(response.content)

    def delete(self, rel: str) -> bool:
        response = self.session.request("DELETE", self.remote_url(rel), timeout=30, **self._auth_kwargs())
        if response.status_code in {200, 202, 204, 404}:
            return response.status_code != 404
        raise ImageStorageError(f"WebDAV DELETE failed: HTTP {response.status_code}")

    def test(self) -> dict[str, object]:
        if not self.url:
            return {"ok": False, "status": 0, "error": "WebDAV URL is required"}
        if urlparse(self.url).scheme not in {"http", "https"}:
            return {"ok": False, "status": 0, "error": "invalid WebDAV URL"}
        test_rel = ".miaowazzImage_webdav_test.txt"
        try:
            self.put(test_rel, b"miaowazzImage webdav test\n", content_type="text/plain")
            self.delete(test_rel)
            return {"ok": True, "status": 200, "error": None}
        except ImageStorageError as exc:
            return {"ok": False, "status": 0, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "status": 0, "error": str(exc) or exc.__class__.__name__}
        finally:
            self.session.close()


def _r2_endpoint_from_env() -> str:
    value = _clean(os.getenv("R2_ENDPOINT_URL")).rstrip("/")
    if value and not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value


class R2Client:
    def __init__(self) -> None:
        self.endpoint = _r2_endpoint_from_env()
        self.access_key_id = _clean(os.getenv("R2_ACCESS_KEY_ID"))
        self.secret_access_key = _clean(os.getenv("R2_SECRET_ACCESS_KEY"))
        self.region = _clean(os.getenv("R2_REGION")) or "auto"
        self.bucket = _clean(os.getenv("R2_BUCKET"))
        self.session = requests.Session(impersonate="chrome", verify=True)

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint and self.access_key_id and self.secret_access_key and self.bucket)

    def validate(self) -> None:
        missing = []
        if not self.endpoint:
            missing.append("R2_ENDPOINT_URL")
        if not self.access_key_id:
            missing.append("R2_ACCESS_KEY_ID")
        if not self.secret_access_key:
            missing.append("R2_SECRET_ACCESS_KEY")
        if not self.bucket:
            missing.append("R2_BUCKET")
        if missing:
            raise ImageStorageError(f"R2 配置不完整：缺少 {', '.join(missing)}")

    @staticmethod
    def _sha256_hex(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _hmac_sha256(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

    def _sign_headers(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str]]:
        now = datetime.utcnow()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        encoded_query = urlencode(sorted((query or {}).items()))
        payload_hash = self._sha256_hex(body)
        host = urlparse(self.endpoint).netloc
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if extra_headers:
            for key, value in extra_headers.items():
                headers[key.lower()] = str(value).strip()
        sorted_items = sorted((key.lower(), " ".join(str(value).strip().split())) for key, value in headers.items())
        canonical_headers = "".join(f"{key}:{value}\n" for key, value in sorted_items)
        signed_headers = ";".join(key for key, _ in sorted_items)
        canonical_request = "\n".join([method.upper(), path, encoded_query, canonical_headers, signed_headers, payload_hash])
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            self._sha256_hex(canonical_request.encode("utf-8")),
        ])
        k_date = self._hmac_sha256(("AWS4" + self.secret_access_key).encode("utf-8"), date_stamp)
        k_region = hmac.new(k_date, self.region.encode("utf-8"), hashlib.sha256).digest()
        k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        return encoded_query, headers

    def _request(
        self,
        method: str,
        key: str = "",
        *,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        extra_headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ):
        self.validate()
        object_path = f"/{self.bucket}"
        if key:
            object_path += f"/{quote(_safe_relative_path(key), safe='/')}"
        encoded_query, headers = self._sign_headers(method, object_path, query=query, body=body, extra_headers=extra_headers)
        url = f"{self.endpoint}{object_path}"
        if encoded_query:
            url += f"?{encoded_query}"
        return self.session.request(method.upper(), url, headers=headers, data=body, timeout=timeout)

    def put(self, rel: str, payload: bytes, content_type: str = "image/png") -> str:
        response = self._request("PUT", rel, body=payload, extra_headers={"content-type": content_type})
        if response.status_code >= 400:
            raise ImageStorageError(f"R2 PUT failed: HTTP {response.status_code}")
        return rel

    def get(self, rel: str) -> bytes:
        response = self._request("GET", rel)
        if response.status_code >= 400:
            raise ImageStorageError(f"R2 GET failed: HTTP {response.status_code}")
        return bytes(response.content or b"")

    def delete(self, rel: str) -> bool:
        response = self._request("DELETE", rel, timeout=30.0)
        if response.status_code in {200, 202, 204, 404}:
            return response.status_code != 404
        raise ImageStorageError(f"R2 DELETE failed: HTTP {response.status_code}")

    def test(self) -> dict[str, object]:
        try:
            self.validate()
            test_rel = ".miaowazzImage_r2_image_test.txt"
            self.put(test_rel, b"miaowazzImage r2 image test\n", content_type="text/plain")
            self.delete(test_rel)
            return {"ok": True, "status": 200, "error": None}
        except Exception as exc:
            return {"ok": False, "status": 0, "error": str(exc) or exc.__class__.__name__}
        finally:
            self.session.close()


class ImageStorageService:
    def __init__(self, index_file: Path = IMAGE_INDEX_FILE):
        self.index_file = index_file
        self._index_lock = IMAGE_INDEX_LOCK
        self._list_cache: dict[tuple[str, str, str], tuple[float, list[dict[str, object]]]] = {}
        init_app_database()
        self._migrate_legacy_index()

    def settings(self) -> dict[str, object]:
        return config.get_image_storage_settings()

    def mode(self) -> str:
        return _clean(self.settings().get("mode")) or "local"

    def _load_index(self) -> dict[str, dict[str, object]]:
        raw = _read_json_object(self.index_file)
        items = raw.get("items")
        if not isinstance(items, dict):
            return {}
        return {str(key): value for key, value in items.items() if isinstance(value, dict)}

    def _load_clean_index(self) -> dict[str, dict[str, object]]:
        items = self._load_index()
        return {rel: item for rel, item in items.items() if _is_image_rel(rel)}

    def _save_index(self, items: dict[str, dict[str, object]]) -> None:
        _write_json_object(self.index_file, {"items": items})

    @staticmethod
    def _row_to_item(row: ImageRecordModel) -> dict[str, object]:
        item: dict[str, object] = {
            "rel": row.rel,
            "path": row.rel,
            "name": row.name,
            "date": row.date,
            "size": int(row.size or 0),
            "created_at": row.created_at,
            "storage": row.storage,
            "local": bool(row.local),
            "webdav": bool(row.webdav),
            "r2": bool(row.r2),
            "remote_url": row.remote_url,
            "owner_id": row.owner_id,
            "task_id": row.task_id,
        }
        if row.width:
            item["width"] = int(row.width)
        if row.height:
            item["height"] = int(row.height)
        return item

    def _get_db_item(self, rel: str, *, include_deleted: bool = False) -> dict[str, object] | None:
        safe_rel = _safe_relative_path(rel)
        session = SessionLocal()
        try:
            query = session.query(ImageRecordModel).filter(ImageRecordModel.rel == safe_rel)
            if not include_deleted:
                query = query.filter(ImageRecordModel.deleted_at.is_(None))
            row = query.first()
            return self._row_to_item(row) if row is not None else None
        finally:
            session.close()

    def _save_db_item(self, item: dict[str, object]) -> None:
        session = SessionLocal()
        try:
            rel = _safe_relative_path(str(item.get("rel") or item.get("path") or ""))
            row = session.query(ImageRecordModel).filter(ImageRecordModel.rel == rel).first()
            values = {
                "name": str(item.get("name") or Path(rel).name),
                "date": str(item.get("date") or "-".join(rel.split("/")[:3]))[:10],
                "size": int(item.get("size") or 0),
                "created_at": str(item.get("created_at") or _now_iso())[:19],
                "storage": str(item.get("storage") or "r2"),
                "local": bool(item.get("local")),
                "webdav": bool(item.get("webdav")),
                "r2": bool(item.get("r2")),
                "remote_url": str(item.get("remote_url") or ""),
                "owner_id": str(item.get("owner_id") or ""),
                "task_id": str(item.get("task_id") or ""),
                "width": int(item["width"]) if item.get("width") else None,
                "height": int(item["height"]) if item.get("height") else None,
                "deleted_at": None,
            }
            if row is None:
                row = ImageRecordModel(rel=rel, **values)
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            session.commit()
            self._list_cache.clear()
        finally:
            session.close()

    def _migrate_legacy_index(self) -> None:
        if not self.index_file.exists():
            return
        session = SessionLocal()
        try:
            if session.query(ImageRecordModel).count() > 0:
                return
        finally:
            session.close()
        for rel, item in self._load_clean_index().items():
            if not isinstance(item, dict):
                continue
            self._save_db_item({
                **item,
                "rel": rel,
                "path": rel,
                "name": str(item.get("name") or Path(rel).name),
                "date": str(item.get("date") or "-".join(rel.split("/")[:3]))[:10],
                "created_at": str(item.get("created_at") or _now_iso())[:19],
            })

    def _public_url(self, rel: str, base_url: str | None = None, owner_id: str = "") -> str:
        settings = self.settings()
        public_base_url = _clean(settings.get("public_base_url"))
        if public_base_url:
            return f"{public_base_url.rstrip('/')}/{_safe_relative_path(rel)}"
        url = f"{(base_url or config.base_url).rstrip('/')}/images/{_safe_relative_path(rel)}"
        if owner_id:
            url += f"?token={create_asset_access_token(owner_id=owner_id, rel=_safe_relative_path(rel))}"
        return url

    def make_relative_path(self, image_data: bytes) -> str:
        file_hash = hashlib.md5(image_data).hexdigest()
        filename = f"{int(time.time())}_{file_hash}.png"
        relative_dir = Path(time.strftime("%Y"), time.strftime("%m"), time.strftime("%d"))
        return f"{relative_dir.as_posix()}/{filename}"

    def save(self, image_data: bytes, base_url: str | None = None, owner_id: str = "", task_id: str = "") -> StoredImage:
        config.cleanup_old_images()
        rel = self.make_relative_path(image_data)
        mode = self.mode()
        r2_client = R2Client()
        r2_enabled = r2_client.enabled
        if r2_enabled:
            mode = "r2"
        if mode not in {"local", "webdav", "both", "r2"}:
            mode = "local"
        stored_local = False
        stored_webdav = False
        stored_r2 = False
        remote_url = ""

        if mode in {"local", "both"}:
            path = _local_image_path(rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(image_data)
            stored_local = True

        if mode in {"webdav", "both"}:
            remote_url = WebDAVClient(self.settings()).put(rel, image_data)
            stored_webdav = True

        if mode == "r2":
            remote_url = R2Client().put(rel, image_data)
            stored_r2 = True

        dimensions = _image_dimensions(image_data)
        storage = "r2" if stored_r2 else ("both" if stored_local and stored_webdav else ("webdav" if stored_webdav else "local"))
        item = {
            "rel": rel,
            "path": rel,
            "name": Path(rel).name,
            "date": "-".join(rel.split("/")[:3]),
            "size": len(image_data),
            "created_at": _now_iso(),
            "storage": storage,
            "local": stored_local,
            "webdav": stored_webdav,
            "r2": stored_r2,
            "remote_url": remote_url,
            "owner_id": owner_id,
            "task_id": task_id,
        }
        if dimensions:
            item["width"], item["height"] = dimensions
        if owner_id:
            user_service.record_generated_asset(
                user_id=owner_id,
                rel=rel,
                task_id=task_id,
                filename=Path(rel).name,
                content_type="image/png",
                size=len(image_data),
                width=dimensions[0] if dimensions else None,
                height=dimensions[1] if dimensions else None,
            )
        self._save_db_item(item)
        return StoredImage(rel=rel, url=self._public_url(rel, base_url, owner_id), storage=str(item["storage"]), size=len(image_data))

    def get_bytes(self, rel: str) -> bytes:
        safe_rel = _safe_relative_path(rel)
        if not _is_image_rel(safe_rel):
            raise HTTPException(status_code=404, detail="image not found")
        item = self._get_db_item(safe_rel)
        if item is None:
            raise HTTPException(status_code=404, detail="image not found")
        path = _local_image_path(safe_rel)
        if item.get("local") and path.is_file():
            return path.read_bytes()
        if item.get("webdav"):
            return WebDAVClient(self.settings()).get(safe_rel)
        if item.get("r2"):
            return R2Client().get(safe_rel)
        raise HTTPException(status_code=404, detail="image not found")

    def exists(self, rel: str) -> bool:
        safe_rel = _safe_relative_path(rel)
        if not _is_image_rel(safe_rel):
            return False
        item = self._get_db_item(safe_rel)
        return item is not None and bool(item.get("local") or item.get("webdav") or item.get("r2"))

    def has_local(self, rel: str) -> bool:
        safe_rel = _safe_relative_path(rel)
        item = self._get_db_item(safe_rel)
        return bool(item and item.get("local") and _is_image_rel(safe_rel) and _local_image_path(safe_rel).is_file())

    def list_items(self, base_url: str, start_date: str = "", end_date: str = "") -> list[dict[str, object]]:
        cache_key = (str(base_url or ""), str(start_date or ""), str(end_date or ""))
        cached = self._list_cache.get(cache_key)
        if cached and cached[0] > time.time():
            return [dict(item) for item in cached[1]]
        session = SessionLocal()
        try:
            query = session.query(ImageRecordModel).filter(ImageRecordModel.deleted_at.is_(None))
            if start_date:
                query = query.filter(ImageRecordModel.date >= start_date)
            if end_date:
                query = query.filter(ImageRecordModel.date <= end_date)
            rows = query.order_by(ImageRecordModel.created_at.desc()).all()
            items: list[dict[str, object]] = []
            for row in rows:
                item = self._row_to_item(row)
                rel = str(item["rel"])
                owner_id = str(item.get("owner_id") or "")
                items.append({
                    **item,
                    "rel": rel,
                    "path": rel,
                    "owner_id": owner_id,
                    "url": self._public_url(rel, base_url, owner_id or "admin"),
                })
            self._list_cache[cache_key] = (time.time() + 30, [dict(item) for item in items])
            return items
        finally:
            session.close()

    def delete(self, rel: str) -> bool:
        safe_rel = _safe_relative_path(rel)
        session = SessionLocal()
        try:
            row = (
                session.query(ImageRecordModel)
                .filter(ImageRecordModel.rel == safe_rel, ImageRecordModel.deleted_at.is_(None))
                .first()
            )
            if row is None:
                return False
            row.deleted_at = datetime.now()
            session.commit()
            self._list_cache.clear()
            return True
        finally:
            session.close()

    def sync_all(self) -> dict[str, int]:
        settings = self.settings()
        if self.mode() not in {"webdav", "both"}:
            raise ImageStorageError("WebDAV 图片存储未启用")
        uploaded = 0
        skipped = 0
        failed = 0
        with self._index_lock:
            items = self._load_clean_index()
            client = WebDAVClient(settings)
            for path in sorted(config.images_dir.rglob("*")):
                if not path.is_file() or not _is_image_rel(path.name):
                    continue
                rel = path.relative_to(config.images_dir).as_posix()
                item = items.get(rel, {})
                if item.get("webdav"):
                    skipped += 1
                    continue
                try:
                    payload = path.read_bytes()
                    remote_url = client.put(rel, payload)
                    dimensions = _image_dimensions(payload)
                    items[rel] = {
                        **item,
                        "rel": rel,
                        "path": rel,
                        "name": path.name,
                        "date": "-".join(rel.split("/")[:3]) if len(rel.split("/")) >= 4 else datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d"),
                        "size": len(payload),
                        "created_at": str(item.get("created_at") or datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")),
                        "storage": "both",
                        "local": True,
                        "webdav": True,
                        "remote_url": remote_url,
                        **({"width": dimensions[0], "height": dimensions[1]} if dimensions else {}),
                    }
                    uploaded += 1
                except Exception:
                    failed += 1
            self._save_index(items)
        return {"uploaded": uploaded, "skipped": skipped, "failed": failed}

    def test_webdav(self) -> dict[str, object]:
        return WebDAVClient(self.settings()).test()


image_storage_service = ImageStorageService()
