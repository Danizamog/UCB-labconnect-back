from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.entities.user import User
from app.infrastructure.security.password import hash_password, verify_password


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _new_id() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(15))


class PostgresUserRepository:
    def __init__(self, *, postgres_url: str, namespace: str = "labconnect") -> None:
        self._postgres_url = postgres_url
        self._namespace = namespace or "labconnect"
        self._collection = "users"
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
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_local_records_collection
                ON local_records(namespace, collection, deleted)
                """
            )

    def _to_user(self, data: dict[str, Any]) -> User:
        role_name, permissions = self._resolve_role(
            str(data.get("role") or "").strip(),
            fallback_role_name=str(data.get("role_name") or "").strip(),
        )
        return User(
            id=str(data.get("id") or ""),
            username=str(data.get("email") or data.get("username") or "").strip().lower(),
            hashed_password=str(data.get("hashed_password") or ""),
            name=(str(data.get("name") or "").strip() or None),
            role=role_name,
            profile_type=(str(data.get("profile_type") or "").strip() or None),
            phone=(str(data.get("phone") or "").strip() or None),
            academic_page=(str(data.get("academic_page") or "").strip() or None),
            faculty=(str(data.get("faculty") or "").strip() or None),
            career=(str(data.get("career") or "").strip() or None),
            student_code=(str(data.get("student_code") or "").strip() or None),
            campus=(str(data.get("campus") or "").strip() or None),
            bio=(str(data.get("bio") or "").strip() or None),
            is_active=bool(data.get("is_active", True)),
            created_at=data.get("created"),
            updated_at=data.get("updated"),
            permissions=permissions or list(data.get("permissions") or []),
        )

    def _resolve_role(self, raw_role: str, *, fallback_role_name: str = "") -> tuple[str | None, list[str]]:
        normalized_role = str(raw_role or "").strip()
        fallback_name = str(fallback_role_name or "").strip()
        if not normalized_role and not fallback_name:
            return None, []

        role_aliases = {
            "admin": "Administrador",
            "user": "Estudiante",
            "student": "Estudiante",
            "teacher": "Docente",
            "lab_manager": "Encargado de Laboratorio",
            "guest": "Invitado",
        }
        role_lookup = role_aliases.get(normalized_role.lower(), normalized_role) if normalized_role else ""
        role_candidates = [candidate for candidate in [role_lookup, fallback_name] if candidate]

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT data FROM local_records
                WHERE namespace = %s AND collection = 'role' AND deleted = FALSE
                """,
                (self._namespace,),
            ).fetchall()

        for candidate in role_candidates:
            for row in rows:
                data = dict(row["data"])
                role_id = str(data.get("id") or "").strip()
                role_name = str(data.get("nombre") or data.get("name") or "").strip()
                if role_id == candidate or role_name.lower() == candidate.lower():
                    permisos = data.get("permisos") or data.get("permissions") or []
                    return role_name or candidate, [str(item).strip() for item in permisos if str(item).strip()]

        return role_candidates[0] if role_candidates else None, []

    def _from_user(self, user: User, *, hashed_password: str | None = None) -> dict[str, Any]:
        now = _now_iso()
        email = user.username.strip().lower()
        return {
            "id": user.id or _new_id(),
            "email": email,
            "username": email,
            "name": user.name or email.split("@")[0],
            "hashed_password": hashed_password if hashed_password is not None else user.hashed_password,
            "role": user.role or "",
            "role_name": user.role or "",
            "profile_type": user.profile_type or "",
            "phone": user.phone or "",
            "academic_page": user.academic_page or "",
            "faculty": user.faculty or "",
            "career": user.career or "",
            "student_code": user.student_code or "",
            "campus": user.campus or "",
            "bio": user.bio or "",
            "is_active": bool(user.is_active),
            "verified": True,
            "emailVisibility": True,
            "permissions": list(user.permissions or []),
            "created": user.created_at or now,
            "updated": now,
        }

    def _save_data(self, data: dict[str, Any], *, operation: str) -> User:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO local_records(namespace, collection, id, data, deleted, updated_at)
                VALUES (%s, %s, %s, %s, FALSE, now())
                ON CONFLICT(namespace, collection, id)
                DO UPDATE SET data = EXCLUDED.data, deleted = FALSE, updated_at = now()
                """,
                (self._namespace, self._collection, data["id"], Jsonb(data)),
            )
            conn.execute(
                """
                INSERT INTO sync_outbox(namespace, collection, record_id, operation, payload)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (self._namespace, self._collection, data["id"], operation, Jsonb(data)),
            )
        return self._to_user(data)

    def _upsert_shadow_data(self, conn, data: dict[str, Any]) -> dict[str, Any]:
        conn.execute(
            """
            INSERT INTO local_records(namespace, collection, id, data, deleted, updated_at)
            VALUES (%s, %s, %s, %s, FALSE, now())
            ON CONFLICT(namespace, collection, id)
            DO UPDATE SET data = EXCLUDED.data, deleted = FALSE, updated_at = now()
            """,
            (self._namespace, self._collection, data["id"], Jsonb(data)),
        )
        return data

    def _shadow_row_by_id(self, conn, user_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT data FROM local_records
            WHERE namespace = %s AND collection = %s AND id = %s
            """,
            (self._namespace, self._collection, user_id),
        ).fetchone()
        return dict(row["data"]) if row else None

    def _shadow_row_by_email(self, conn, username: str) -> dict[str, Any] | None:
        normalized = username.strip().lower()
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
            (self._namespace, self._collection, normalized),
        ).fetchone()
        return dict(row["data"]) if row else None

    def _mark_duplicate_emails_deleted(self, conn, *, email: str, keep_id: str) -> None:
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
            (self._namespace, self._collection, keep_id, normalized),
        )

    def _role_ids_by_name(self, conn) -> dict[str, str]:
        rows = conn.execute(
            """
            SELECT data
            FROM local_records
            WHERE namespace = %s AND collection = 'role' AND deleted = FALSE
            """,
            (self._namespace,),
        ).fetchall()
        mapping: dict[str, str] = {}
        duplicates: set[str] = set()
        for row in rows:
            data = dict(row["data"])
            role_id = str(data.get("id") or "").strip()
            role_name = str(data.get("nombre") or data.get("name") or "").strip().lower()
            if not role_id or not role_name:
                continue
            if role_name in mapping and mapping[role_name] != role_id:
                duplicates.add(role_name)
                mapping.pop(role_name, None)
                continue
            if role_name not in duplicates:
                mapping[role_name] = role_id
        return mapping

    def mirror_users_from_primary(
        self,
        users: list[User],
        *,
        role_ids_by_name: dict[str, str] | None = None,
    ) -> int:
        mirrored = 0

        with self._connect() as conn:
            resolved_role_ids = {key.strip().lower(): value for key, value in (role_ids_by_name or {}).items() if key and value}
            if not resolved_role_ids:
                resolved_role_ids = self._role_ids_by_name(conn)

            for user in users:
                email = str(user.username or "").strip().lower()
                user_id = str(user.id or "").strip()
                if not email or not user_id:
                    continue

                existing = self._shadow_row_by_id(conn, user_id) or self._shadow_row_by_email(conn, email) or {}
                role_name = str(user.role or "").strip()
                role_id = resolved_role_ids.get(role_name.lower(), "") if role_name else ""

                data = dict(existing)
                data.update(
                    {
                        "id": user_id,
                        "email": email,
                        "username": email,
                        "name": user.name or existing.get("name") or email.split("@")[0],
                        "hashed_password": str(existing.get("hashed_password") or ""),
                        "role": role_id or role_name,
                        "role_name": role_name,
                        "profile_type": user.profile_type or existing.get("profile_type") or "",
                        "phone": user.phone or existing.get("phone") or "",
                        "academic_page": user.academic_page or existing.get("academic_page") or "",
                        "faculty": user.faculty or existing.get("faculty") or "",
                        "career": user.career or existing.get("career") or "",
                        "student_code": user.student_code or existing.get("student_code") or "",
                        "campus": user.campus or existing.get("campus") or "",
                        "bio": user.bio or existing.get("bio") or "",
                        "is_active": bool(user.is_active),
                        "verified": existing.get("verified", True),
                        "emailVisibility": existing.get("emailVisibility", True),
                        "permissions": list(user.permissions or existing.get("permissions") or []),
                        "created": user.created_at or existing.get("created") or _now_iso(),
                        "updated": user.updated_at or _now_iso(),
                    }
                )

                self._upsert_shadow_data(conn, data)
                self._mark_duplicate_emails_deleted(conn, email=email, keep_id=user_id)
                mirrored += 1

        return mirrored

    def _row_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT data FROM local_records
                WHERE namespace = %s AND collection = %s AND id = %s AND deleted = FALSE
                """,
                (self._namespace, self._collection, user_id),
            ).fetchone()
        return dict(row["data"]) if row else None

    def _row_by_email(self, username: str) -> dict[str, Any] | None:
        normalized = username.strip().lower()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT data FROM local_records
                WHERE namespace = %s AND collection = %s AND deleted = FALSE
                """,
                (self._namespace, self._collection),
            ).fetchall()
        for row in rows:
            data = dict(row["data"])
            if str(data.get("email") or data.get("username") or "").strip().lower() == normalized:
                return data
        return None

    def get_by_id(self, user_id: str) -> User | None:
        data = self._row_by_id(user_id.strip())
        return self._to_user(data) if data else None

    def list_all(self) -> list[User]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT data FROM local_records
                WHERE namespace = %s AND collection = %s AND deleted = FALSE
                ORDER BY updated_at DESC
                """,
                (self._namespace, self._collection),
            ).fetchall()
        return [self._to_user(dict(row["data"])) for row in rows]

    def get_by_username(self, username: str) -> User | None:
        data = self._row_by_email(username)
        return self._to_user(data) if data else None

    def save(self, user: User) -> User:
        existing = self.get_by_username(user.username)
        base_user = existing or user
        data = self._from_user(
            User(
                id=base_user.id or user.id,
                username=user.username,
                hashed_password=base_user.hashed_password,
                name=user.name or base_user.name,
                role=user.role or base_user.role,
                profile_type=user.profile_type or base_user.profile_type,
                phone=user.phone or base_user.phone,
                academic_page=user.academic_page or base_user.academic_page,
                faculty=user.faculty or base_user.faculty,
                career=user.career or base_user.career,
                student_code=user.student_code or base_user.student_code,
                campus=user.campus or base_user.campus,
                bio=user.bio or base_user.bio,
                is_active=user.is_active,
                permissions=list(user.permissions or base_user.permissions or []),
                created_at=base_user.created_at,
            )
        )
        return self._save_data(data, operation="update" if existing else "create")

    def save_with_password(self, user: User, password: str) -> User:
        existing = self.get_by_username(user.username)
        hashed_password = hash_password(password)
        data = self._from_user(
            User(
                id=existing.id if existing else user.id,
                username=user.username,
                name=user.name or (existing.name if existing else None),
                role=user.role or (existing.role if existing else None),
                profile_type=user.profile_type or (existing.profile_type if existing else None),
                phone=user.phone or (existing.phone if existing else None),
                academic_page=user.academic_page or (existing.academic_page if existing else None),
                faculty=user.faculty or (existing.faculty if existing else None),
                career=user.career or (existing.career if existing else None),
                student_code=user.student_code or (existing.student_code if existing else None),
                campus=user.campus or (existing.campus if existing else None),
                bio=user.bio or (existing.bio if existing else None),
                is_active=user.is_active,
                permissions=list(user.permissions or (existing.permissions if existing else []) or []),
                created_at=existing.created_at if existing else None,
            ),
            hashed_password=hashed_password,
        )
        return self._save_data(data, operation="update" if existing else "create")

    def authenticate(self, username: str, password: str) -> User | None:
        data = self._row_by_email(username)
        if not data:
            return None
        stored_hash = str(data.get("hashed_password") or "")
        if not stored_hash or not verify_password(password, stored_hash):
            return None
        user = self._to_user(data)
        if not user.is_active:
            return None
        return user

    def delete(self, user_id: str) -> bool:
        normalized_id = user_id.strip()
        if not normalized_id:
            return False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (normalized_id,))
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted
