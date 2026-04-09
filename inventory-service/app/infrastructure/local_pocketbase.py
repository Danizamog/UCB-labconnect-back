from __future__ import annotations

import math
import re
import secrets
import string
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


_LIST_RE = re.compile(r"^/api/collections/(?P<collection>[^/]+)/records/?$")
_ONE_RE = re.compile(r"^/api/collections/(?P<collection>[^/]+)/records/(?P<record_id>[^/]+)/?$")
_COLLECTION_RE = re.compile(r"^/api/collections/(?P<collection>[^/]+)/?$")
_AUTH_RE = re.compile(r"^/api/(?:collections/(?P<collection>[^/]+)/)?auth-with-password$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _new_id() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(15))


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "none", "null"}
    return bool(value)


class LocalPocketBaseFallback:
    """PostgreSQL-backed PocketBase-shaped fallback used when the remote API is down."""

    def __init__(self, *, postgres_url: str, namespace: str, enabled: bool = True) -> None:
        self.postgres_url = postgres_url.strip()
        self.namespace = namespace.strip() or "labconnect"
        self.enabled = enabled and bool(self.postgres_url)
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
            self._seed_inventory_defaults(conn)
            conn.execute("SELECT pg_advisory_unlock(48271042)")
        self._initialized = True

    def _seed_inventory_defaults(self, conn) -> None:
        self._seed_record(
            conn,
            "area",
            "area_general",
            {"name": "UCB San Pablo - La Paz", "description": "Campus La Paz", "is_active": True},
            outbox=False,
        )
        labs = [
            ("lab_fisica", "Laboratorio de Fisica", "Bloque académico", 39),
            ("lab_quimica", "Laboratorio de Quimica", "Bloque académico", 30),
            ("lab_sistemas", "Laboratorio de Sistemas", "Bloque académico", 35),
        ]
        for lab_id, name, location, capacity in labs:
            self._seed_record(
                conn,
                "laboratory",
                lab_id,
                {
                    "name": name,
                    "location": location,
                    "capacity": capacity,
                    "description": "Laboratorio operativo local mientras PocketBase remoto se recupera.",
                    "is_active": True,
                    "area_id": "area_general",
                    "allowed_roles": [],
                    "allowed_user_ids": [],
                    "required_permissions": [],
                },
                outbox=False,
            )

    def _seed_record(self, conn, collection: str, record_id: str, payload: dict[str, Any], *, outbox: bool) -> dict[str, Any]:
        exists = conn.execute(
            """
            SELECT data FROM local_records
            WHERE namespace = %s AND collection = %s AND id = %s AND deleted = FALSE
            """,
            (self.namespace, collection, record_id),
        ).fetchone()
        if exists:
            return dict(exists["data"])
        return self._upsert_record(conn, collection, record_id, payload, operation="seed" if outbox else None)

    def _upsert_record(
        self,
        conn,
        collection: str,
        record_id: str,
        payload: dict[str, Any],
        *,
        operation: str | None,
    ) -> dict[str, Any]:
        existing = conn.execute(
            """
            SELECT data FROM local_records
            WHERE namespace = %s AND collection = %s AND id = %s
            """,
            (self.namespace, collection, record_id),
        ).fetchone()
        now = _now_iso()
        data = dict(existing["data"]) if existing else {}
        data.update(payload or {})
        data["id"] = record_id
        data["collectionName"] = collection
        data.setdefault("created", now)
        data["updated"] = now
        conn.execute(
            """
            INSERT INTO local_records(namespace, collection, id, data, deleted, updated_at)
            VALUES (%s, %s, %s, %s, FALSE, now())
            ON CONFLICT(namespace, collection, id)
            DO UPDATE SET data = EXCLUDED.data, deleted = FALSE, updated_at = now()
            """,
            (self.namespace, collection, record_id, Jsonb(data)),
        )
        if operation in {"create", "update", "delete"}:
            conn.execute(
                """
                INSERT INTO sync_outbox(namespace, collection, record_id, operation, payload)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (self.namespace, collection, record_id, operation, Jsonb(data)),
            )
        return data

    def _delete_record(self, conn, collection: str, record_id: str) -> None:
        payload = {"id": record_id, "deleted": True}
        conn.execute(
            """
            UPDATE local_records
            SET deleted = TRUE, updated_at = now()
            WHERE namespace = %s AND collection = %s AND id = %s
            """,
            (self.namespace, collection, record_id),
        )
        conn.execute(
            """
            INSERT INTO sync_outbox(namespace, collection, record_id, operation, payload)
            VALUES (%s, %s, %s, 'delete', %s)
            """,
            (self.namespace, collection, record_id, Jsonb(payload)),
        )

    def _list_records(self, conn, collection: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT data FROM local_records
            WHERE namespace = %s AND collection = %s AND deleted = FALSE
            """,
            (self.namespace, collection),
        ).fetchall()
        return [dict(row["data"]) for row in rows]

    def _get_record(self, conn, collection: str, record_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT data FROM local_records
            WHERE namespace = %s AND collection = %s AND id = %s AND deleted = FALSE
            """,
            (self.namespace, collection, record_id),
        ).fetchone()
        return dict(row["data"]) if row else None

    def _matches_filter(self, record: dict[str, Any], raw_filter: str | None) -> bool:
        if not raw_filter:
            return True
        clauses = re.split(r"\s+&&\s+|\s+AND\s+", raw_filter)
        for clause in clauses:
            text = clause.strip().strip("()")
            if not text:
                continue
            match = re.match(r'(?P<field>[a-zA-Z_][\w]*)\s*(?P<op>=|!=|~|>=|<=|>|<)\s*["\']?(?P<value>[^"\']+)["\']?$', text)
            if not match:
                continue
            field = match.group("field")
            op = match.group("op")
            expected = match.group("value").strip()
            actual = record.get(field)
            actual_text = "" if actual is None else str(actual)
            if op == "=" and actual_text != expected:
                return False
            if op == "!=" and actual_text == expected:
                return False
            if op == "~" and expected.lower() not in actual_text.lower():
                return False
            if op in {">", "<", ">=", "<="}:
                if op == ">" and actual_text <= expected:
                    return False
                if op == "<" and actual_text >= expected:
                    return False
                if op == ">=" and actual_text < expected:
                    return False
                if op == "<=" and actual_text > expected:
                    return False
        return True

    def _apply_expand(self, conn, collection: str, record: dict[str, Any], expand: str | None) -> dict[str, Any]:
        if not expand:
            return record
        expanded = dict(record)
        expand_payload: dict[str, Any] = dict(expanded.get("expand") or {})
        for field in [item.strip() for item in expand.split(",") if item.strip()]:
            ref_id = str(record.get(field) or "").strip()
            if not ref_id:
                continue
            ref_collection = {
                "area_id": "area",
                "laboratory_id": "laboratory",
                "role": "role",
            }.get(field, field)
            ref = self._get_record(conn, ref_collection, ref_id)
            if ref:
                expand_payload[field] = ref
        if expand_payload:
            expanded["expand"] = expand_payload
        return expanded

    def _sort_records(self, records: list[dict[str, Any]], sort: str | None) -> list[dict[str, Any]]:
        if not sort:
            return records
        sorted_records = list(records)
        for field_spec in reversed([item.strip() for item in sort.split(",") if item.strip()]):
            reverse = field_spec.startswith("-")
            field = field_spec[1:] if reverse else field_spec
            sorted_records.sort(key=lambda item: str(item.get(field) or ""), reverse=reverse)
        return sorted_records

    def handle(self, method: str, path: str, *, payload: dict | None = None, params: dict | None = None) -> dict | list | None:
        self._ensure_schema()
        method = method.upper()
        params = dict(params or {})
        if _AUTH_RE.match(path):
            return {"token": "local-postgres-fallback-token", "record": {"id": "local-admin"}}

        collection_match = _COLLECTION_RE.match(path)
        if collection_match and method == "GET":
            collection = collection_match.group("collection")
            return {"id": collection, "name": collection, "type": "base", "fields": []}
        if path.rstrip("/") == "/api/collections" and method == "POST":
            return {"id": (payload or {}).get("name", _new_id()), **(payload or {})}

        one_match = _ONE_RE.match(path)
        list_match = _LIST_RE.match(path)

        with self._connect() as conn:
            if one_match:
                collection = one_match.group("collection")
                record_id = one_match.group("record_id")
                if method == "GET":
                    record = self._get_record(conn, collection, record_id)
                    if record is None:
                        return None
                    return self._apply_expand(conn, collection, record, params.get("expand"))
                if method == "PATCH":
                    return self._upsert_record(conn, collection, record_id, payload or {}, operation="update")
                if method == "DELETE":
                    self._delete_record(conn, collection, record_id)
                    return None

            if list_match:
                collection = list_match.group("collection")
                if method == "GET":
                    page = max(int(params.get("page", 1) or 1), 1)
                    per_page = max(int(params.get("perPage", params.get("per_page", 50)) or 50), 1)
                    records = [
                        self._apply_expand(conn, collection, record, params.get("expand"))
                        for record in self._list_records(conn, collection)
                        if self._matches_filter(record, params.get("filter"))
                    ]
                    records = self._sort_records(records, params.get("sort"))
                    total_items = len(records)
                    total_pages = max(math.ceil(total_items / per_page), 1)
                    start = (page - 1) * per_page
                    end = start + per_page
                    return {
                        "page": page,
                        "perPage": per_page,
                        "totalItems": total_items,
                        "totalPages": total_pages,
                        "items": records[start:end],
                    }
                if method == "POST":
                    record_id = str((payload or {}).get("id") or _new_id())
                    return self._upsert_record(conn, collection, record_id, payload or {}, operation="create")

        return None

    def sync_pending(self, *, base_url: str, client, headers_factory) -> None:
        if not self.enabled or not base_url:
            return
        self._ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, collection, record_id, operation, payload
                FROM sync_outbox
                WHERE namespace = %s AND status = 'pending'
                ORDER BY created_at
                LIMIT 25
                """,
                (self.namespace,),
            ).fetchall()
            for row in rows:
                try:
                    collection = row["collection"]
                    record_id = row["record_id"]
                    payload = dict(row["payload"])
                    operation = row["operation"]
                    if operation == "delete":
                        client.request("DELETE", f"{base_url}/api/collections/{collection}/records/{record_id}", headers=headers_factory())
                    elif operation == "update":
                        client.request("PATCH", f"{base_url}/api/collections/{collection}/records/{record_id}", json=payload, headers=headers_factory())
                    elif operation == "create":
                        client.request("POST", f"{base_url}/api/collections/{collection}/records", json=payload, headers=headers_factory())
                    conn.execute(
                        "UPDATE sync_outbox SET status = 'synced', processed_at = now(), error = NULL WHERE id = %s",
                        (row["id"],),
                    )
                except Exception as exc:  # pragma: no cover - best effort sync with external service
                    conn.execute(
                        """
                        UPDATE sync_outbox
                        SET attempts = attempts + 1, error = %s
                        WHERE id = %s
                        """,
                        (str(exc)[:500], row["id"]),
                    )
