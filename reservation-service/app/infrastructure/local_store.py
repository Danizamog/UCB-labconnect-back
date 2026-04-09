from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings


class LocalJsonStore:
    """Small JSONB-backed store for durable local operation when PocketBase is unavailable."""

    def __init__(self, collection: str) -> None:
        self.collection = collection
        self.namespace = settings.local_data_namespace
        self.postgres_url = settings.postgres_url
        self.enabled = settings.data_mode in {"hybrid", "postgres", "local"} and bool(self.postgres_url)
        self._initialized = False

    def _connect(self):
        return psycopg.connect(self.postgres_url, row_factory=dict_row)

    def _ensure_schema(self) -> None:
        if not self.enabled or self._initialized:
            return

        with self._connect() as conn:
            conn.execute("SELECT pg_advisory_lock(48271042)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS local_records (
                    namespace TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    id TEXT NOT NULL,
                    data JSONB NOT NULL,
                    deleted BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (namespace, collection, id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_outbox (
                    id BIGSERIAL PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    processed_at TIMESTAMPTZ
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_local_records_collection
                ON local_records(namespace, collection, deleted)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sync_outbox_pending
                ON sync_outbox(namespace, status, created_at)
                """
            )
            conn.execute("SELECT pg_advisory_unlock(48271042)")

        self._initialized = True

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
