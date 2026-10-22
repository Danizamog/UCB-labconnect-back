from typing import Any, Protocol

from app.domain.entities.role import Role


class RoleRepository(Protocol):
    def list_all(self) -> list[Role]:
        ...

    def get_by_id(self, role_id: str) -> Role | None:
        ...

    def get_by_nombre(self, nombre: str) -> Role | None:
        ...

    def create(self, role: Role) -> Role:
        ...

    def update(self, role: Role) -> Role:
        ...

    def delete(self, role_id: str) -> None:
        ...

    def list_users_with_roles(self) -> list[dict[str, Any]]:
        ...

    def assign_user_role(self, user_id: str, role_id: str | None) -> dict[str, Any] | None:
        ...
