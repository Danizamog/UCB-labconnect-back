from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class AsyncRefCountedLockRegistry:
    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}
        self._refcounts: dict[str, int] = {}

    async def _acquire_entry(self, key: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            self._refcounts[key] = self._refcounts.get(key, 0) + 1
            return lock

    async def _release_entry(self, key: str) -> None:
        async with self._guard:
            remaining = self._refcounts.get(key, 0) - 1
            if remaining <= 0:
                self._refcounts.pop(key, None)
                self._locks.pop(key, None)
            else:
                self._refcounts[key] = remaining

    @asynccontextmanager
    async def lock(self, key: str) -> AsyncIterator[None]:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            yield
            return
        entry = await self._acquire_entry(normalized_key)
        try:
            async with entry:
                yield
        finally:
            await self._release_entry(normalized_key)


laboratory_lock_registry = AsyncRefCountedLockRegistry()
