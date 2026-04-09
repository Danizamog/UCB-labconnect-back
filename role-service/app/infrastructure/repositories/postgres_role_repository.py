from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.entities.role import Role


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _new_id() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(15))


class PostgresRoleRepository:
    def __init__(self, *, postgres_url: str, namespace: str = "labconnect") -> None:
        self._postgres_url = postgres_url
        self._namespace = namespace or "labconnect"
        self._role_collection = "role"
        self._users_collection = "users"
        self._ensure_schema()

    def _connect(self):
        return psycopg.connect(self._postgres_url, row_factory=dict_row)

    def _ensure_schema(self) -> None:
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
            conn.execute("SELECT pg_advisory_unlock(48271042)")
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

    def _to_role(self, data: dict[str, Any]) -> Role:
        return Role(
            id=str(data.get("id") or ""),
            nombre=str(data.get("nombre") or data.get("name") or ""),
            descripcion=data.get("descripcion"),
            permisos=[str(item).strip() for item in data.get("permisos", []) if str(item).strip()],
        )

    def _role_payload(self, role: Role) -> dict[str, Any]:
        now = _now_iso()
        return {
            "id": role.id or _new_id(),
            "name": role.nombre,
            "nombre": role.nombre,
            "descripcion": role.descripcion or "",
            "permisos": list(role.permisos or []),
            "created": now,
            "updated": now,
        }

    def _save_record(self, collection: str, record_id: str, payload: dict[str, Any], operation: str) -> dict[str, Any]:
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT data FROM local_records
                WHERE namespace = %s AND collection = %s AND id = %s
                """,
                (self._namespace, collection, record_id),
            ).fetchone()
            data = dict(existing["data"]) if existing else {}
            data.update(payload)
            data["id"] = record_id
            data.setdefault("created", _now_iso())
            data["updated"] = _now_iso()
            conn.execute(
                """
                INSERT INTO local_records(namespace, collection, id, data, deleted, updated_at)
                VALUES (%s, %s, %s, %s, FALSE, now())
                ON CONFLICT(namespace, collection, id)
                DO UPDATE SET data = EXCLUDED.data, deleted = FALSE, updated_at = now()
                """,
                (self._namespace, collection, record_id, Jsonb(data)),
            )
            conn.execute(
                """
                INSERT INTO sync_outbox(namespace, collection, record_id, operation, payload)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (self._namespace, collection, record_id, operation, Jsonb(data)),
            )
        return data

    def _upsert_shadow_record(self, conn, collection: str, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = conn.execute(
            """
            SELECT data FROM local_records
            WHERE namespace = %s AND collection = %s AND id = %s
            """,
            (self._namespace, collection, record_id),
        ).fetchone()
        data = dict(existing["data"]) if existing else {}
        data.update(payload)
        data["id"] = record_id
        data.setdefault("created", _now_iso())
        data["updated"] = payload.get("updated") or _now_iso()
        conn.execute(
            """
            INSERT INTO local_records(namespace, collection, id, data, deleted, updated_at)
            VALUES (%s, %s, %s, %s, FALSE, now())
            ON CONFLICT(namespace, collection, id)
            DO UPDATE SET data = EXCLUDED.data, deleted = FALSE, updated_at = now()
            """,
            (self._namespace, collection, record_id, Jsonb(data)),
        )
        return data

    def _list_collection(self, collection: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT data FROM local_records
                WHERE namespace = %s AND collection = %s AND deleted = FALSE
                ORDER BY updated_at DESC
                """,
                (self._namespace, collection),
            ).fetchall()
        return [dict(row["data"]) for row in rows]

    def _get_record(self, collection: str, record_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT data FROM local_records
                WHERE namespace = %s AND collection = %s AND id = %s AND deleted = FALSE
                """,
                (self._namespace, collection, record_id),
            ).fetchone()
        return dict(row["data"]) if row else None

    def _mark_duplicate_users_deleted(self, conn, *, email: str, keep_id: str) -> None:
        normalized = str(email or "").strip().lower()
        if not normalized or not keep_id:
            return

        conn.execute(
            """
            UPDATE local_records
            SET deleted = TRUE, updated_at = now()
            WHERE namespace = %s
              AND collection = %s
              AND deleted = FALSE
              AND id <> %s
              AND lower(coalesce(data->>'email', data->>'username', '')) = %s
            """,
            (self._namespace, self._users_collection, keep_id, normalized),
        )
    
    def _shadow_user_by_id(self, conn, user_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT data
            FROM local_records
            WHERE namespace = %s AND collection = %s AND id = %s
            """,
            (self._namespace, self._users_collection, user_id),
        ).fetchone()
        return dict(row["data"]) if row else None

    def _is_role_referenced(self, conn, role_id: str) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM local_records
            WHERE namespace = %s
              AND collection = %s
              AND deleted = FALSE
              AND coalesce(data->>'role', '') = %s
            LIMIT 1
            """,
            (self._namespace, self._users_collection, role_id),
        ).fetchone()
        return row is not None

    def _prune_unreferenced_roles_not_in_primary(self, conn, keep_ids: set[str]) -> None:
        rows = conn.execute(
            """
            SELECT id
            FROM local_records
            WHERE namespace = %s AND collection = %s AND deleted = FALSE
            """,
            (self._namespace, self._role_collection),
        ).fetchall()

        for row in rows:
            role_id = str(row["id"] or "").strip()
            if not role_id or role_id in keep_ids or self._is_role_referenced(conn, role_id):
                continue
            conn.execute(
                """
                UPDATE local_records
                SET deleted = TRUE, updated_at = now()
                WHERE namespace = %s AND collection = %s AND id = %s
                """,
                (self._namespace, self._role_collection, role_id),
            )

    def _shadow_user_by_email(self, conn, email: str) -> dict[str, Any] | None:
        normalized = str(email or "").strip().lower()
        row = conn.execute(
            """
            SELECT data
            FROM local_records
            WHERE namespace = %s
              AND collection = %s
              AND lower(coalesce(data->>'email', data->>'username', '')) = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (self._namespace, self._users_collection, normalized),
        ).fetchone()
        return dict(row["data"]) if row else None

    def list_all(self) -> list[Role]:
        return sorted([self._to_role(item) for item in self._list_collection(self._role_collection)], key=lambda role: role.nombre)

    def get_by_id(self, role_id: str) -> Role | None:
        data = self._get_record(self._role_collection, role_id)
        return self._to_role(data) if data else None

    def get_by_nombre(self, nombre: str) -> Role | None:
        normalized = nombre.strip().lower()
        for role in self.list_all():
            if role.nombre.strip().lower() == normalized:
                return role
        return None

    def create(self, role: Role) -> Role:
        if not role.id:
            role.id = _new_id()
        data = self._save_record(self._role_collection, role.id, self._role_payload(role), "create")
        return self._to_role(data)

    def update(self, role: Role) -> Role:
        data = self._save_record(self._role_collection, role.id, self._role_payload(role), "update")
        return self._to_role(data)

    def delete(self, role_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE local_records
                SET deleted = TRUE, updated_at = now()
                WHERE namespace = %s AND collection = %s AND id = %s
                """,
                (self._namespace, self._role_collection, role_id),
            )
            conn.execute(
                """
                INSERT INTO sync_outbox(namespace, collection, record_id, operation, payload)
                VALUES (%s, %s, %s, 'delete', %s)
                """,
                (self._namespace, self._role_collection, role_id, Jsonb({"id": role_id, "deleted": True})),
            )

    def _map_user_record(self, data: dict[str, Any]) -> dict[str, Any]:
        role_id = str(data.get("role") or data.get("roleId") or "").strip() or None
        role = None
        if role_id:
            role = self.get_by_id(role_id) or self.get_by_nombre(role_id)
            if role is None and role_id.lower() == "admin":
                role = self.get_by_nombre("Administrador")
            if role is None and role_id.lower() in {"user", "student"}:
                role = self.get_by_nombre("Estudiante")
            if role is None and role_id.lower() == "teacher":
                role = self.get_by_nombre("Docente")
            if role is None and role_id.lower() == "lab_manager":
                role = self.get_by_nombre("Encargado de Laboratorio")
            if role is None and role_id.lower() == "guest":
                role = self.get_by_nombre("Invitado")
        return {
            "id": data.get("id"),
            "name": data.get("name", ""),
            "email": data.get("email") or data.get("username", ""),
            "roleId": role.id if role else role_id,
            "role": {
                "id": role.id,
                "nombre": role.nombre,
                "descripcion": role.descripcion,
                "permisos": role.permisos,
            } if role else None,
            "created": data.get("created"),
            "updated": data.get("updated"),
        }

    def list_users_with_roles(self) -> list[dict[str, Any]]:
        return [self._map_user_record(item) for item in self._list_collection(self._users_collection)]

    def assign_user_role(self, user_id: str, role_id: str | None) -> dict[str, Any] | None:
        data = self._get_record(self._users_collection, user_id)
        if data is None:
            return None
        role = self.get_by_id(role_id) if role_id else None
        data["role"] = role_id or ""
        data["role_name"] = role.nombre if role else ""
        self._save_record(self._users_collection, user_id, data, "update")
        return self._map_user_record(data)

    def mirror_roles_from_primary(self, roles: list[Role]) -> dict[str, str]:
        role_ids_by_name: dict[str, str] = {}
        seen_ids: set[str] = set()

        with self._connect() as conn:
            for role in roles:
                role_id = str(role.id or "").strip()
                role_name = str(role.nombre or "").strip()
                if not role_id or not role_name:
                    continue

                payload = {
                    "id": role_id,
                    "name": role_name,
                    "nombre": role_name,
                    "descripcion": role.descripcion or "",
                    "permisos": list(role.permisos or []),
                }
                self._upsert_shadow_record(conn, self._role_collection, role_id, payload)
                role_ids_by_name[role_name.lower()] = role_id
                seen_ids.add(role_id)

            self._prune_unreferenced_roles_not_in_primary(conn, seen_ids)

        return role_ids_by_name

    def mirror_users_from_primary(self, users: list[dict[str, Any]]) -> int:
        mirrored = 0

        with self._connect() as conn:
            for user in users:
                user_id = str(user.get("id") or "").strip()
                email = str(user.get("email") or "").strip().lower()
                if not user_id or not email:
                    continue

                existing = self._shadow_user_by_id(conn, user_id) or self._shadow_user_by_email(conn, email) or {}
                role_payload = user.get("role") if isinstance(user.get("role"), dict) else None
                role_id = str(user.get("roleId") or "").strip()
                role_name = str((role_payload or {}).get("nombre") or "").strip()
                permissions = list((role_payload or {}).get("permisos") or [])

                payload = dict(existing)
                payload.update(
                    {
                        "id": user_id,
                        "email": email,
                        "username": email,
                        "name": str(user.get("name") or existing.get("name") or email.split("@")[0]).strip(),
                        "role": role_id,
                        "role_name": role_name,
                        "permissions": permissions,
                        "created": user.get("created") or existing.get("created") or _now_iso(),
                        "updated": user.get("updated") or _now_iso(),
                    }
                )

                self._upsert_shadow_record(conn, self._users_collection, user_id, payload)
                self._mark_duplicate_users_deleted(conn, email=email, keep_id=user_id)
                mirrored += 1

        return mirrored
