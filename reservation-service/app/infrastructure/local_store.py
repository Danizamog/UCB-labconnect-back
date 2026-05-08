from __future__ import annotations

from typing import Any

from app.core.config import settings


def _psycopg():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg, dict_row


def Jsonb(value):
    from psycopg.types.json import Jsonb as _Jsonb
    return _Jsonb(value)


class LocalJsonStore:
    """Small JSONB-backed store for durable local operation when PocketBase is unavailable."""

    def __init__(self, collection: str) -> None:
        self.collection = collection
        self.namespace = settings.local_data_namespace
        self.postgres_url = settings.postgres_url
        self.enabled = settings.data_mode in {"hybrid", "postgres", "local"} and bool(self.postgres_url)
        self._initialized = False

    def _connect(self):
        psycopg, dict_row = _psycopg()
        return psycopg.connect(self.postgres_url, row_factory=dict_row)

    def _ensure_schema(self) -> None:
        return

    def list(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        self._ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT data FROM local_records
                WHERE namespace = %s AND collection = %s AND deleted = FALSE
                ORDER BY updated_at DESC
                """,
                (self.namespace, self.collection),
            ).fetchall()
        return [dict(row["data"]) for row in rows]

    def upsert(self, record_id: str, payload: dict[str, Any], *, operation: str = "update") -> None:
        if not self.enabled:
            return
        self._ensure_schema()
        data = dict(payload)
        data["id"] = record_id
        data.setdefault("collectionName", self.collection)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO local_records(namespace, collection, id, data, deleted, updated_at)
                VALUES (%s, %s, %s, %s, FALSE, now())
                ON CONFLICT(namespace, collection, id)
                DO UPDATE SET data = EXCLUDED.data, deleted = FALSE, updated_at = now()
                """,
                (self.namespace, self.collection, record_id, Jsonb(data)),
            )
            if operation in {"create", "update", "delete"}:
                conn.execute(
                    """
                    INSERT INTO sync_outbox(namespace, collection, record_id, operation, payload)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (self.namespace, self.collection, record_id, operation, Jsonb(data)),
                )

    def delete(self, record_id: str) -> None:
        if not self.enabled:
            return
        self._ensure_schema()
        payload = {"id": record_id, "deleted": True}
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE local_records
                SET deleted = TRUE, updated_at = now()
                WHERE namespace = %s AND collection = %s AND id = %s
                """,
                (self.namespace, self.collection, record_id),
            )
            conn.execute(
                """
                INSERT INTO sync_outbox(namespace, collection, record_id, operation, payload)
                VALUES (%s, %s, %s, 'delete', %s)
                """,
                (self.namespace, self.collection, record_id, Jsonb(payload)),
            )
