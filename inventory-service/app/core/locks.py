from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator


class RefCountedLockRegistry:
    def __init__(self) -> None:
        self._guard = Lock()
        self._locks: dict[str, Lock] = {}
        self._refcounts: dict[str, int] = {}

    def _acquire_entry(self, key: str) -> Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = Lock()
                self._locks[key] = lock
            self._refcounts[key] = self._refcounts.get(key, 0) + 1
            return lock

    def _release_entry(self, key: str) -> None:
        with self._guard:
            remaining = self._refcounts.get(key, 0) - 1
            if remaining <= 0:
                self._refcounts.pop(key, None)
                self._locks.pop(key, None)
            else:
                self._refcounts[key] = remaining

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            yield
            return
        entry = self._acquire_entry(normalized_key)
        try:
            entry.acquire()
            try:
                yield
            finally:
                entry.release()
        finally:
            self._release_entry(normalized_key)


stock_item_lock_registry = RefCountedLockRegistry()
