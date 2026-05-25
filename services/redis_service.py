from __future__ import annotations

import os
import secrets
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse


def _clean(value: object) -> str:
    return str(value or "").strip()


def _encode_command(*parts: object) -> bytes:
    chunks = [f"*{len(parts)}\r\n".encode("utf-8")]
    for part in parts:
        payload = str(part).encode("utf-8")
        chunks.append(f"${len(payload)}\r\n".encode("utf-8"))
        chunks.append(payload + b"\r\n")
    return b"".join(chunks)


@dataclass(frozen=True)
class RedisConfig:
    host: str
    port: int
    password: str
    db: int


class RedisClient:
    def __init__(self, url: str = "") -> None:
        self.url = _clean(url or os.getenv("REDIS_URL"))
        self.config = self._parse_url(self.url) if self.url else None

    @staticmethod
    def _parse_url(url: str) -> RedisConfig:
        parsed = urlparse(url)
        if parsed.scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must start with redis:// or rediss://")
        db = 0
        if parsed.path and parsed.path.strip("/"):
            db = int(parsed.path.strip("/") or 0)
        return RedisConfig(
            host=parsed.hostname or "127.0.0.1",
            port=int(parsed.port or 6379),
            password=unquote(parsed.password or ""),
            db=db,
        )

    @property
    def enabled(self) -> bool:
        return self.config is not None

    def _request(self, *parts: object, timeout: float = 2.0) -> Any:
        if self.config is None:
            return None
        with socket.create_connection((self.config.host, self.config.port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            if self.config.password:
                sock.sendall(_encode_command("AUTH", self.config.password))
                self._read_response(sock)
            if self.config.db:
                sock.sendall(_encode_command("SELECT", self.config.db))
                self._read_response(sock)
            sock.sendall(_encode_command(*parts))
            return self._read_response(sock)

    def _read_response(self, sock: socket.socket) -> Any:
        prefix = sock.recv(1)
        if not prefix:
            raise RuntimeError("empty redis response")
        if prefix == b"+":
            return self._read_line(sock).decode("utf-8", errors="replace")
        if prefix == b"-":
            raise RuntimeError(self._read_line(sock).decode("utf-8", errors="replace"))
        if prefix == b":":
            return int(self._read_line(sock))
        if prefix == b"$":
            length = int(self._read_line(sock))
            if length < 0:
                return None
            payload = self._read_exact(sock, length)
            self._read_exact(sock, 2)
            return payload.decode("utf-8", errors="replace")
        if prefix == b"*":
            count = int(self._read_line(sock))
            return [self._read_response(sock) for _ in range(count)]
        raise RuntimeError("unsupported redis response")

    @staticmethod
    def _read_line(sock: socket.socket) -> bytes:
        data = bytearray()
        while True:
            chunk = sock.recv(1)
            if not chunk:
                raise RuntimeError("redis connection closed")
            data.extend(chunk)
            if data.endswith(b"\r\n"):
                return bytes(data[:-2])

    @staticmethod
    def _read_exact(sock: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise RuntimeError("redis connection closed")
            data.extend(chunk)
        return bytes(data)

    def ping(self) -> bool:
        if not self.enabled:
            return False
        return self._request("PING") == "PONG"

    def acquire_lock(self, key: str, ttl_seconds: int = 300) -> str:
        if not self.enabled:
            return ""
        value = secrets.token_urlsafe(18)
        result = self._request("SET", key, value, "NX", "EX", max(1, int(ttl_seconds or 300)))
        return value if result == "OK" else ""

    def release_lock(self, key: str, value: str) -> None:
        if not self.enabled or not value:
            return
        try:
            current = self._request("GET", key)
            if current == value:
                self._request("DEL", key)
        except Exception:
            pass


redis_client = RedisClient()
