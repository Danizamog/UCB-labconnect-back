import httpx
from typing import Any

from app.domain.entities.role import Role


class PocketBaseRoleRepository:
    def __init__(
        self,
        base_url: str,
        collection: str = "role",
        users_collection: str = "users",
        auth_token: str | None = None,
        auth_identity: str | None = None,
        auth_password: str | None = None,
        auth_collection: str = "_superusers",
        timeout_seconds: float = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._collection = collection
        self._users_collection = users_collection
        self._timeout = timeout_seconds
        self._auth_identity = auth_identity
        self._auth_password = auth_password
        self._auth_collection = auth_collection
        self._auth_token = auth_token
        self._client = httpx.Client(
            timeout=httpx.Timeout(self._timeout, connect=min(self._timeout, 5.0)),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    def _build_headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        merged_headers = dict(headers or {})
        if self._auth_token:
            merged_headers["Authorization"] = f"Bearer {self._auth_token}"
        return merged_headers

    def _has_credentials(self) -> bool:
        return bool(self._auth_identity and self._auth_password)

    def _auth_endpoint(self) -> str:
        return f"{self._base_url}/api/collections/{self._auth_collection}/auth-with-password"

    def _authenticate(self) -> None:
        if not self._has_credentials():
            return

        payload = {
            "identity": self._auth_identity,
            "password": self._auth_password,
        }

        auth_endpoints = [self._auth_endpoint()]
        if self._auth_collection in {"_superusers", "admins"}:
            auth_endpoints.append(f"{self._base_url}/api/admins/auth-with-password")

        last_exception: Exception | None = None
        for endpoint in auth_endpoints:
            try:
                response = self._client.request("POST", endpoint, json=payload)
                response.raise_for_status()
                data = response.json() if response.content else {}
                token = data.get("token") if isinstance(data, dict) else None
                if not token:
                    raise ValueError("PocketBase no devolvió token en auth-with-password")
                self._auth_token = token
                return
            except httpx.HTTPStatusError as exc:
                last_exception = exc
                if exc.response.status_code == 404:
                    continue
                raise

        if last_exception:
            raise last_exception
        raise ValueError("No se pudo autenticar contra PocketBase")

    def _records_endpoint(self) -> str:
        return f"{self._base_url}/api/collections/{self._collection}/records"

    def _users_endpoint(self) -> str:
        return f"{self._base_url}/api/collections/{self._users_collection}/records"

    def _request(self, method: str, url: str, **kwargs) -> dict | list | None:
        headers = kwargs.pop("headers", {})

        if not self._auth_token and self._has_credentials():
            self._authenticate()

        response = self._client.request(
            method,
            url,
            headers=self._build_headers(headers),
            **kwargs,
        )

        if response.status_code == 401 and self._has_credentials():
            self._authenticate()
            response = self._client.request(
                method,
                url,
                headers=self._build_headers(headers),
                **kwargs,
            )

        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    @staticmethod
    def _to_role(record: dict) -> Role:
        permisos = record.get("permisos")
        if not isinstance(permisos, list):
            permisos = []

        return Role(
            id=record["id"],
            nombre=record.get("nombre") or record.get("name", ""),
            descripcion=record.get("descripcion"),
            permisos=[str(item).strip() for item in permisos if str(item).strip()],
        )

    def list_all(self) -> list[Role]:
        roles: list[Role] = []
        page = 1

        while True:
            try:
                payload = self._request(
                    "GET",
                    self._records_endpoint(),
                    params={"page": page, "perPage": 200, "sort": "name"},
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 400:
                    raise
                payload = self._request(
                    "GET",
                    self._records_endpoint(),
                    params={"page": page, "perPage": 200, "sort": "nombre"},
                )
            if not isinstance(payload, dict):
                return roles

            items = payload.get("items", [])
            roles.extend(self._to_role(item) for item in items)

            if page >= int(payload.get("totalPages", 1)):
                break
            page += 1

        return roles

    def get_by_id(self, role_id: str) -> Role | None:
        try:
            payload = self._request("GET", f"{self._records_endpoint()}/{role_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

        if not isinstance(payload, dict):
            return None
        return self._to_role(payload)

    def get_by_nombre(self, nombre: str) -> Role | None:
        normalized = nombre.strip()
        if not normalized:
            return None

        escaped = normalized.replace('"', '\\"')
        try:
            payload = self._request(
                "GET",
                self._records_endpoint(),
                params={"page": 1, "perPage": 1, "filter": f'name="{escaped}"'},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            if exc.response.status_code == 400:
                payload = self._request(
                    "GET",
                    self._records_endpoint(),
                    params={"page": 1, "perPage": 1, "filter": f'nombre="{escaped}"'},
                )
            else:
                raise

        if not isinstance(payload, dict):
            return None

        items = payload.get("items", [])
        if not items:
            return None
        return self._to_role(items[0])

    def create(self, role: Role) -> Role:
        try:
            payload = self._request(
                "POST",
                self._records_endpoint(),
                json={
                    "name": role.nombre,
                    "descripcion": role.descripcion,
                    "permisos": role.permisos,
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            payload = self._request(
                "POST",
                self._records_endpoint(),
                json={
                    "nombre": role.nombre,
                    "descripcion": role.descripcion,
                    "permisos": role.permisos,
                },
            )
        if not isinstance(payload, dict):
            raise ValueError("PocketBase devolvió una respuesta inválida al crear el rol")
        return self._to_role(payload)

    def update(self, role: Role) -> Role:
        try:
            payload = self._request(
                "PATCH",
                f"{self._records_endpoint()}/{role.id}",
                json={
                    "name": role.nombre,
                    "descripcion": role.descripcion,
                    "permisos": role.permisos,
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            payload = self._request(
                "PATCH",
                f"{self._records_endpoint()}/{role.id}",
                json={
                    "nombre": role.nombre,
                    "descripcion": role.descripcion,
                    "permisos": role.permisos,
                },
            )
        if not isinstance(payload, dict):
            raise ValueError("PocketBase devolvió una respuesta inválida al actualizar el rol")
        return self._to_role(payload)

    def delete(self, role_id: str) -> None:
        self._request("DELETE", f"{self._records_endpoint()}/{role_id}")

    @staticmethod
    def _map_user_record(record: dict[str, Any]) -> dict[str, Any]:
        expanded_role = record.get("expand", {}).get("role") if isinstance(record.get("expand"), dict) else None
        role_ref = record.get("role")

        mapped_role = None
        if isinstance(expanded_role, dict):
            permisos = expanded_role.get("permisos")
            if not isinstance(permisos, list):
                permisos = []

            mapped_role = {
                "id": expanded_role.get("id"),
                "nombre": expanded_role.get("nombre") or expanded_role.get("name", ""),
                "descripcion": expanded_role.get("descripcion"),
                "permisos": [str(item).strip() for item in permisos if str(item).strip()],
            }

        role_id = role_ref if isinstance(role_ref, str) else None

        return {
            "id": record.get("id"),
            "name": record.get("name", ""),
            "email": record.get("email", ""),
            "roleId": role_id,
            "role": mapped_role,
            "created": record.get("created"),
            "updated": record.get("updated"),
        }

    def list_users_with_roles(self) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = []
        page = 1

        while True:
            payload = self._request(
                "GET",
                self._users_endpoint(),
                params={"page": page, "perPage": 200, "expand": "role", "sort": "name"},
            )

            if not isinstance(payload, dict):
                return users

            items = payload.get("items", [])
            users.extend(self._map_user_record(item) for item in items)

            if page >= int(payload.get("totalPages", 1)):
                break
            page += 1

        return users

    def assign_user_role(self, user_id: str, role_id: str | None) -> dict[str, Any] | None:
        try:
            self._request(
                "PATCH",
                f"{self._users_endpoint()}/{user_id}",
                json={"role": role_id or None},
            )
            payload = self._request(
                "GET",
                f"{self._users_endpoint()}/{user_id}",
                params={"expand": "role"},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

        if not isinstance(payload, dict):
            return None

        return self._map_user_record(payload)

    def close(self) -> None:
        self._client.close()
