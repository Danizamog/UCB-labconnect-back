from __future__ import annotations

import time
from copy import deepcopy
from threading import Lock
from typing import Callable, Generic, TypeVar

T = TypeVar("T")

_MISSING = object()


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = max(float(ttl_seconds), 0.0)
        self._items: dict[object, tuple[float, T]] = {}
        self._lock = Lock()

    def get(self, key: object) -> T | object:
        now = time.monotonic()
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return _MISSING

            expires_at, value = entry
            if expires_at <= now:
                self._items.pop(key, None)
                return _MISSING

            return deepcopy(value)

    def set(self, key: object, value: T) -> T:
        expires_at = time.monotonic() + self._ttl_seconds
        stored = deepcopy(value)
        with self._lock:
            self._items[key] = (expires_at, stored)
        return deepcopy(stored)

    def get_or_set(self, key: object, loader: Callable[[], T]) -> T:
        cached = self.get(key)
        if cached is not _MISSING:
            return cached

        value = loader()
        return self.set(key, value)

    def invalidate(self, predicate: Callable[[object], bool] | None = None) -> None:
        with self._lock:
            if predicate is None:
                self._items.clear()
                return

            keys_to_delete = [key for key in self._items if predicate(key)]
            for key in keys_to_delete:
                self._items.pop(key, None)
