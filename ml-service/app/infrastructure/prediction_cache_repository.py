from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.infrastructure.pocketbase_client import PocketBaseClient

logger = logging.getLogger(__name__)

_pb = PocketBaseClient()
_COLLECTION = settings.cache_collection


def close() -> None:
    _pb.close()


def _escape(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _find(kind: str, target_id: str) -> dict[str, Any] | None:
    rows = _pb.list_records(
        _COLLECTION,
        filter=f'kind = "{_escape(kind)}" && target_id = "{_escape(target_id)}"',
        per_page=1,
        max_items=1,
    )
    return rows[0] if rows else None


def read(kind: str, target_id: str = "") -> dict[str, Any] | None:
    """Devuelve el payload guardado (dict) o None si no existe."""
    row = _find(kind, target_id)
    if not row:
        return None
    payload = row.get("payload")
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload:
        try:
            return json.loads(payload)
        except ValueError:
            return None
    return None


def is_fresh(payload: dict[str, Any]) -> bool:
    timestamp = payload.get("generated_at")
    if not timestamp:
        return False
    try:
        generated = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return False
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - generated).total_seconds()
    return age <= settings.cache_max_age_seconds


def upsert(kind: str, target_id: str, payload: dict[str, Any], confidence: str = "") -> None:
    record = {
        "kind": kind,
        "target_id": target_id,
        "payload": payload,
        "confidence": confidence,
        "generated_at": str(payload.get("generated_at") or ""),
    }
    existing = _find(kind, target_id)
    if existing:
        _pb.update_record(_COLLECTION, str(existing["id"]), record)
    else:
        _pb.create_record(_COLLECTION, record)


def ensure_collection() -> bool:
    """Verifica que la coleccion exista (creada a mano en el Admin UI).

    No la crea: el esquema ya fue definido en PocketBase. Devuelve True si existe."""
    try:
        exists = _pb.get_collection(_COLLECTION) is not None
    except Exception:
        logger.exception("ml-service: no se pudo verificar la coleccion %s", _COLLECTION)
        return False
    if not exists:
        logger.error(
            "ml-service: la coleccion '%s' no existe en PocketBase. Crea la coleccion base "
            "con los campos kind, target_id, payload(json), confidence, generated_at.",
            _COLLECTION,
        )
    return exists
