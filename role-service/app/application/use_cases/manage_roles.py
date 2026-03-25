from typing import Any

from app.domain.entities.role import Role
from app.domain.repositories.role_repository import RoleRepository


class ManageRolesUseCase:
    def __init__(self, repository: RoleRepository):
        self.repository = repository

    def list_roles(self) -> list[Role]:
        return self.repository.list_all()

    def get_role(self, role_id: str) -> Role:
        role = self.repository.get_by_id(role_id)
        if not role:
            raise LookupError("Rol no encontrado")
        return role

    def create_role(self, nombre: str, descripcion: str | None, permisos: list[str]) -> Role:
        normalized_nombre = nombre.strip()
        if not normalized_nombre:
            raise ValueError("El nombre del rol es obligatorio")

        if self.repository.get_by_nombre(normalized_nombre):
            raise ValueError("Ya existe un rol con ese nombre")

        role = Role(
            id="",
            nombre=normalized_nombre,
            descripcion=descripcion,
            permisos=sorted(set(permission.strip() for permission in permisos if permission.strip())),
        )
        return self.repository.create(role)

    def update_role(self, role_id: str, nombre: str, descripcion: str | None, permisos: list[str]) -> Role:
        role = self.repository.get_by_id(role_id)
        if not role:
            raise LookupError("Rol no encontrado")

        normalized_nombre = nombre.strip()
        if not normalized_nombre:
            raise ValueError("El nombre del rol es obligatorio")

        role_with_same_name = self.repository.get_by_nombre(normalized_nombre)
        if role_with_same_name and role_with_same_name.id != role_id:
            raise ValueError("Ya existe un rol con ese nombre")

        role.nombre = normalized_nombre
        role.descripcion = descripcion
        role.permisos = sorted(set(permission.strip() for permission in permisos if permission.strip()))
        return self.repository.update(role)

    def delete_role(self, role_id: str) -> None:
        if not self.repository.get_by_id(role_id):
            raise LookupError("Rol no encontrado")
        self.repository.delete(role_id)

    def list_users_with_roles(self) -> list[dict[str, Any]]:
        return self.repository.list_users_with_roles()

    def assign_user_role(self, user_id: str, role_id: str | None) -> dict[str, Any]:
        user = self.repository.assign_user_role(user_id=user_id, role_id=role_id)
        if not user:
            raise LookupError("Usuario no encontrado")
        return user
