from __future__ import annotations

from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row


class UserDirectoryRepository:
    def __init__(self, *, postgres_url: str, namespace: str = "labconnect", auth_service_url: str = "") -> None:
        self._postgres_url = postgres_url.strip()
        self._namespace = namespace.strip() or "labconnect"
        self._auth_service_url = auth_service_url.strip().rstrip("/")
        self._http_client = httpx.Client(
            timeout=httpx.Timeout(5.0, connect=3.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    def _connect(self):
        return psycopg.connect(self._postgres_url, row_factory=dict_row)

    def _normalize_user(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(data.get("id") or "").strip(),
            "name": str(data.get("name") or data.get("username") or data.get("email") or "").strip(),
            "email": str(data.get("email") or data.get("username") or "").strip().lower(),
            "role": str(data.get("role_name") or data.get("role") or data.get("profile_type") or "").strip(),
            "profile_type": str(data.get("profile_type") or "").strip(),
            "student_code": str(data.get("student_code") or "").strip(),
            "is_active": bool(data.get("is_active", True)),
        }

    def _list_local_users(self) -> list[dict[str, Any]]:
        if not self._postgres_url:
            return []

        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT data
                    FROM local_records
                    WHERE namespace = %s AND collection = 'users' AND deleted = FALSE
                    """,
                    (self._namespace,),
                ).fetchall()
        except psycopg.Error:
            return []

        return [self._normalize_user(dict(row["data"])) for row in rows]

    def _list_remote_users(self, access_token: str) -> list[dict[str, Any]]:
        token = str(access_token or "").strip()
        if not self._auth_service_url or not token:
            return []

        try:
            response = self._http_client.get(
                f"{self._auth_service_url}/v1/users/",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError:
            return []

        if response.status_code >= 400:
            return []

        try:
            body = response.json()
        except ValueError:
            return []

        if not isinstance(body, list):
            return []

        return [self._normalize_user(item) for item in body if isinstance(item, dict)]

    @staticmethod
    def _matches(user: dict[str, Any], identifiers: set[str]) -> bool:
        user_id = str(user.get("id") or "").strip().lower()
        email = str(user.get("email") or "").strip().lower()
        student_code = str(user.get("student_code") or "").strip().lower()
        return bool({value for value in {user_id, email, student_code} if value}.intersection(identifiers))

    def resolve(self, *, identifier: str, email: str = "", access_token: str = "") -> dict[str, Any] | None:
        identifiers = {
            str(identifier or "").strip().lower(),
            str(email or "").strip().lower(),
        }
        identifiers.discard("")
        if not identifiers:
            return None

        for user in self._list_local_users():
            if self._matches(user, identifiers):
                return user

        for user in self._list_remote_users(access_token):
            if self._matches(user, identifiers):
                return user

        return None
