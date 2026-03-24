import httpx

from app.domain.entities.role import Role


class PocketBaseRoleRepository:
    def __init__(
        self,
        base_url: str,
        collection: str = "role",
        auth_token: str | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._collection = collection
        self._timeout = timeout_seconds
        self._headers: dict[str, str] = {}
        if auth_token:
            self._headers["Authorization"] = f"Bearer {auth_token}"

    def _records_endpoint(self) -> str:
        return f"{self._base_url}/api/collections/{self._collection}/records"

    def _request(self, method: str, url: str, **kwargs) -> dict | list | None:
        headers = kwargs.pop("headers", {})
        merged_headers = {**self._headers, **headers}
        response = httpx.request(method, url, headers=merged_headers, timeout=self._timeout, **kwargs)
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
            nombre=record.get("nombre", ""),
            descripcion=record.get("descripcion"),
            permisos=[str(item).strip() for item in permisos if str(item).strip()],
        )

    def list_all(self) -> list[Role]:
        roles: list[Role] = []
        page = 1

        while True:
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
                params={"page": 1, "perPage": 1, "filter": f'nombre="{escaped}"'},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

        if not isinstance(payload, dict):
            return None

        items = payload.get("items", [])
        if not items:
            return None
        return self._to_role(items[0])

    def create(self, role: Role) -> Role:
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