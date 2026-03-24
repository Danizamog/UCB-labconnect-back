from typing import Protocol

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
