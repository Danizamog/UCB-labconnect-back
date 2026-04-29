import json
from urllib.parse import urlencode

import httpx

from app.domain.entities.user import User


class PocketBaseUserRepository:
    def __init__(
        self,
        base_url: str,
        users_collection: str = "users",
        auth_token: str | None = None,
        auth_identity: str | None = None,
        auth_password: str | None = None,
        auth_collection: str = "_superusers",
        roles_collection: str = "role",
        timeout_seconds: float = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._users_collection = users_collection
        self._roles_collection = roles_collection
        self._timeout = timeout_seconds
        self._auth_identity = auth_identity
        self._auth_password = auth_password
        self._auth_collection = auth_collection
        self._auth_token = auth_token
        self._supported_fields: set[str] | None = None
        self._role_id_cache: dict[str, str] = {}
        self._client = httpx.Client(
            timeout=httpx.Timeout(self._timeout, connect=min(self._timeout, 5.0)),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    def _has_credentials(self) -> bool:
        return bool(self._auth_identity and self._auth_password)

    def _headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _auth_endpoint(self) -> str:
        return f"{self._base_url}/api/collections/{self._auth_collection}/auth-with-password"

    def _users_endpoint(self) -> str:
        return f"{self._base_url}/api/collections/{self._users_collection}"

    def _records_endpoint(self) -> str:
        return f"{self._users_endpoint()}/records"

    def _request(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
        retry_on_auth_error: bool = True,
    ) -> dict | list | None:
        try:
            response = self._client.request(
                method,
                url,
                json=payload,
                headers=self._headers(headers),
            )
            response.raise_for_status()
            raw_body = response.content
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401 and retry_on_auth_error and self._has_credentials():
                self._authenticate()
                return self._request(
                    method,
                    url,
                    payload=payload,
                    headers=headers,
                    retry_on_auth_error=False,
                )
            raise
        except httpx.HTTPError as exc:
            raise ValueError("No se pudo conectar con PocketBase") from exc

        if not raw_body:
            return None
        return json.loads(raw_body.decode("utf-8"))

    @staticmethod
    def _extract_http_status_message(exc: httpx.HTTPStatusError, fallback_message: str) -> str:
        response = exc.response
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()

            data = payload.get("data")
            if isinstance(data, dict):
                first_error = next(iter(data.values()), None)
                if isinstance(first_error, dict):
                    message = first_error.get("message")
                    if isinstance(message, str) and message.strip():
                        return message.strip()

        return fallback_message

    def _authenticate(self) -> None:
        if not self._has_credentials():
            return

        payload = {"identity": self._auth_identity, "password": self._auth_password}
        endpoints = [self._auth_endpoint()]
        if self._auth_collection in {"_superusers", "admins"}:
            endpoints.append(f"{self._base_url}/api/admins/auth-with-password")

        last_error: Exception | None = None
        for endpoint in endpoints:
            try:
                data = self._request("POST", endpoint, payload=payload, retry_on_auth_error=False)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 404:
                    continue
                continue
            except ValueError as exc:
                last_error = exc
                raise

            token = data.get("token") if isinstance(data, dict) else None
            if token:
                self._auth_token = token
                return

        if last_error:
            raise ValueError("No se pudo autenticar contra PocketBase") from last_error
        raise ValueError("No se pudo autenticar contra PocketBase")

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _map_role_name(record: dict) -> str | None:
        expand = record.get("expand")
        if not isinstance(expand, dict):
            return None

        expanded_role = expand.get("role")
        if not isinstance(expanded_role, dict):
            return None

        role_name = expanded_role.get("nombre") or expanded_role.get("name")
        if not isinstance(role_name, str):
            return None
        normalized_role = role_name.strip()
        return normalized_role or None

    def _to_user(self, record: dict) -> User:
        email = str(record.get("email", "")).strip().lower()
        expanded_role = record.get("expand", {}).get("role") if isinstance(record.get("expand"), dict) else None
        permissions = []
        if isinstance(expanded_role, dict):
            role_permissions = expanded_role.get("permisos")
            if isinstance(role_permissions, list):
                permissions = [str(item).strip() for item in role_permissions if str(item).strip()]
        return User(
            id=record.get("id"),
            username=email,
            name=(str(record.get("name", "")).strip() or None),
            role=self._map_role_name(record),
            profile_type=(str(record.get("profile_type", "")).strip() or None),
            phone=(str(record.get("phone", "")).strip() or None),
            academic_page=(str(record.get("academic_page", "")).strip() or None),
            faculty=(str(record.get("faculty", "")).strip() or None),
            career=(str(record.get("career", "")).strip() or None),
            student_code=(str(record.get("student_code", "")).strip() or None),
            campus=(str(record.get("campus", "")).strip() or None),
            bio=(str(record.get("bio", "")).strip() or None),
            is_active=bool(record.get("is_active", True)),
            created_at=record.get("created"),
            updated_at=record.get("updated"),
            permissions=permissions,
        )

    def _fetch_record_by_id(self, user_id: str) -> User | None:
        query = urlencode({"expand": "role"})
        try:
            payload = self._request("GET", f"{self._records_endpoint()}/{user_id}?{query}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(payload, dict):
            return None
        return self._to_user(payload)

    def _ensure_authenticated(self) -> None:
        if self._has_credentials() and not self._auth_token:
            self._authenticate()

    def _load_supported_fields(self) -> set[str]:
        if self._supported_fields is not None:
            return self._supported_fields

        self._ensure_authenticated()

        try:
            payload = self._request("GET", self._users_endpoint())
        except httpx.HTTPStatusError:
            self._supported_fields = set()
            return self._supported_fields

        fields: set[str] = set()
        if isinstance(payload, dict):
            for field in payload.get("fields", []):
                if isinstance(field, dict):
                    name = field.get("name")
                    if isinstance(name, str):
                        fields.add(name)

        self._supported_fields = fields
        return fields

    def _resolve_role_id(self, role_name: str) -> str | None:
        normalized = (role_name or "").strip()
        if not normalized:
            return None

        cache_key = normalized.lower()
        if cache_key in self._role_id_cache:
            return self._role_id_cache[cache_key] or None

        self._ensure_authenticated()
        roles_url = f"{self._base_url}/api/collections/{self._roles_collection}/records"
        params = urlencode(
            {
                "page": 1,
                "perPage": 1,
                "filter": f'name="{self._escape_filter_value(normalized)}"',
            }
        )

        try:
            payload = self._request("GET", f"{roles_url}?{params}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {400, 404}:
                self._role_id_cache[cache_key] = ""
                return None
            raise
        except httpx.RequestError:
            return None

        role_id = ""
        if isinstance(payload, dict):
            items = payload.get("items", [])
            if isinstance(items, list) and items:
                first = items[0]
                if isinstance(first, dict):
                    raw_id = first.get("id")
                    if isinstance(raw_id, str):
                        role_id = raw_id.strip()

        self._role_id_cache[cache_key] = role_id
        return role_id or None

    def _build_payload(self, user: User, password: str | None = None) -> dict:
        name = user.name or user.username.split("@")[0]
        payload = {
            "email": user.username.strip().lower(),
            "name": name,
            "verified": True,
            "emailVisibility": True,
        }
        if password:
            payload["password"] = password
            payload["passwordConfirm"] = password

        supported_fields = self._load_supported_fields()
        optional_fields = {
            "profile_type": user.profile_type,
            "phone": user.phone,
            "academic_page": user.academic_page,
            "faculty": user.faculty,
            "career": user.career,
            "student_code": user.student_code,
            "campus": user.campus,
            "bio": user.bio,
            "is_active": user.is_active,
        }
        for key, value in optional_fields.items():
            if key not in supported_fields:
                continue
            payload[key] = value

        if "role" in supported_fields and user.role:
            role_id = self._resolve_role_id(user.role)
            if role_id:
                payload["role"] = role_id

        return payload

    def get_by_id(self, user_id: str) -> User | None:
        normalized_id = user_id.strip()
        if not normalized_id:
            return None
        self._ensure_authenticated()
        return self._fetch_record_by_id(normalized_id)

    def list_all(self) -> list[User]:
        self._ensure_authenticated()

        page = 1
        users: list[User] = []

        while True:
            params = urlencode(
                {
                    "page": page,
                    "perPage": 200,
                    "expand": "role",
                    "sort": "-created",
                }
            )
            payload = self._request("GET", f"{self._records_endpoint()}?{params}")
            if not isinstance(payload, dict):
                break

            items = payload.get("items", [])
            if not isinstance(items, list) or not items:
                break

            users.extend(self._to_user(item) for item in items if isinstance(item, dict))

            total_pages = int(payload.get("totalPages", page))
            if page >= total_pages:
                break
            page += 1

        return users

    def get_by_username(self, username: str) -> User | None:
        normalized_username = username.strip().lower()
        if not normalized_username:
            return None

        self._ensure_authenticated()

        params = urlencode(
            {
                "page": 1,
                "perPage": 1,
                "expand": "role",
                "filter": f'email="{self._escape_filter_value(normalized_username)}"',
            }
        )

        try:
            payload = self._request("GET", f"{self._records_endpoint()}?{params}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {400, 404}:
                return None
            raise

        if not isinstance(payload, dict):
            return None

        items = payload.get("items", [])
        if not items:
            return None

        return self._to_user(items[0])

    def save(self, user: User) -> User:
        existing_user = user if user.id else self.get_by_username(user.username)
        if not existing_user or not existing_user.id:
            raise ValueError("Se requiere una contrasena para crear el usuario en PocketBase")
        payload = self._build_payload(
            User(
                id=existing_user.id,
                username=user.username,
                name=user.name or existing_user.name,
                role=user.role or existing_user.role,
                profile_type=user.profile_type,
                phone=user.phone,
                academic_page=user.academic_page,
                faculty=user.faculty,
                career=user.career,
                student_code=user.student_code,
                campus=user.campus,
                bio=user.bio,
                is_active=user.is_active,
            )
        )

        try:
            data = self._request("PATCH", f"{self._records_endpoint()}/{existing_user.id}", payload=payload)
        except httpx.HTTPStatusError as exc:
            detail = self._extract_http_status_message(exc, "No se pudo guardar el usuario en PocketBase")
            raise ValueError(detail) from exc
        except httpx.RequestError as exc:
            raise ValueError("No se pudo conectar con PocketBase") from exc

        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al guardar el usuario")

        record_id = data.get("id") if isinstance(data.get("id"), str) else None
        if record_id:
            expanded = self._fetch_record_by_id(record_id)
            if expanded is not None:
                return expanded
        return self._to_user(data)

    def save_with_password(self, user: User, password: str) -> User:
        normalized_username = user.username.strip().lower()
        existing_user = self.get_by_username(normalized_username)
        payload = self._build_payload(
            User(
                id=existing_user.id if existing_user else user.id,
                username=normalized_username,
                name=user.name,
                role=user.role,
                profile_type=user.profile_type,
                phone=user.phone,
                academic_page=user.academic_page,
                faculty=user.faculty,
                career=user.career,
                student_code=user.student_code,
                campus=user.campus,
                bio=user.bio,
                is_active=user.is_active,
            ),
            password=password,
        )

        try:
            if existing_user and existing_user.id:
                data = self._request(
                    "PATCH",
                    f"{self._records_endpoint()}/{existing_user.id}",
                    payload=payload,
                )
            else:
                data = self._request("POST", self._records_endpoint(), payload=payload)
        except httpx.HTTPStatusError as exc:
            detail = self._extract_http_status_message(exc, "No se pudo guardar el usuario en PocketBase")
            raise ValueError(detail) from exc
        except httpx.RequestError as exc:
            raise ValueError("No se pudo conectar con PocketBase") from exc

        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al guardar el usuario")

        record_id = data.get("id") if isinstance(data.get("id"), str) else None
        if record_id:
            expanded = self._fetch_record_by_id(record_id)
            if expanded is not None:
                return expanded
        return self._to_user(data)

    def authenticate(self, username: str, password: str) -> User | None:
        normalized_username = username.strip().lower()
        payload = {"identity": normalized_username, "password": password}

        try:
            data = self._request(
                "POST",
                f"{self._users_endpoint()}/auth-with-password",
                payload=payload,
                headers={"Authorization": ""},
                retry_on_auth_error=False,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {400, 401, 404}:
                return None
            raise

        if not isinstance(data, dict):
            return None

        record = data.get("record")
        if not isinstance(record, dict):
            return None

        user_id = record.get("id")
        if isinstance(user_id, str) and user_id:
            expanded_user = self._fetch_record_by_id(user_id)
            if expanded_user:
                return expanded_user

        return self._to_user(record)

    def close(self) -> None:
        self._client.close()
