"""Small in-process TTL cache for agent classification and tool results."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any


class TtlCache:
    def __init__(self, *, max_items: int = 512, ttl_seconds: float = 600.0):
        self.max_items = max(8, int(max_items))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        now = time.monotonic()
        with self._lock:
            row = self._data.get(key)
            if row is None:
                return None
            expires, value = row
            if expires <= now:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._data) >= self.max_items:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (now + self.ttl_seconds, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def cache_key(*parts: object) -> str:
    raw = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


classify_cache = TtlCache(max_items=512, ttl_seconds=600.0)
