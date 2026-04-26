from __future__ import annotations

import httpx
from time import monotonic

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient

_LAB_ACCESS_CACHE: dict[str, tuple[float, dict | None]] = {}
_LAB_ACCESS_CACHE_TTL_SECONDS = 30
_LAB_ACCESS_CACHE_MAX_ITEMS = 300


def _get_cached_lab(laboratory_id: str) -> dict | None | object:
    cached = _LAB_ACCESS_CACHE.get(laboratory_id)
    if not cached:
        return _CACHE_MISS

    expires_at, data = cached
    if expires_at <= monotonic():
        _LAB_ACCESS_CACHE.pop(laboratory_id, None)
        return _CACHE_MISS

    return dict(data) if isinstance(data, dict) else None


def _set_cached_lab(laboratory_id: str, data: dict | None) -> None:
    if len(_LAB_ACCESS_CACHE) >= _LAB_ACCESS_CACHE_MAX_ITEMS:
        oldest_key = next(iter(_LAB_ACCESS_CACHE))
        _LAB_ACCESS_CACHE.pop(oldest_key, None)

    _LAB_ACCESS_CACHE[laboratory_id] = (monotonic() + _LAB_ACCESS_CACHE_TTL_SECONDS, dict(data) if isinstance(data, dict) else None)


_CACHE_MISS = object()


class LaboratoryAccessRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{settings.pb_laboratory_collection}/records"

    def get_by_id(self, laboratory_id: str) -> dict | None:
        lab_id = str(laboratory_id or "").strip()
        if not lab_id:
            return None

        cached = _get_cached_lab(lab_id)
        if cached is not _CACHE_MISS:
            return cached if isinstance(cached, dict) else None

        try:
            data = self._client.request("GET", f"{self._base}/{lab_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                _set_cached_lab(lab_id, None)
                return None
            raise
        result = data if isinstance(data, dict) else None
        _set_cached_lab(lab_id, result)
        return result
