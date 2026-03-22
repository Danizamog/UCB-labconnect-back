from app.domain.entities.role import Role
from app.domain.repositories.role_repository import RoleRepository


class ManageRolesUseCase:
    def __init__(self, repository: RoleRepository):
        self.repository = repository

    def list_roles(self) -> list[Role]:
        return self.repository.list_all()

    def get_role(self, role_id: int) -> Role:
        role = self.repository.get_by_id(role_id)
        if not role:
            raise LookupError("Rol no encontrado")
        return role

    def create_role(self, name: str, description: str | None, permissions: list[str], is_active: bool) -> Role:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("El nombre del rol es obligatorio")

        if self.repository.get_by_name(normalized_name):
            raise ValueError("Ya existe un rol con ese nombre")

        role = Role(
            id=0,
            name=normalized_name,
            description=description,
            permissions=sorted(set(permission.strip() for permission in permissions if permission.strip())),
            is_active=is_active,
        )
        return self.repository.create(role)

    def update_role(self, role_id: int, name: str, description: str | None, permissions: list[str], is_active: bool) -> Role:
        role = self.repository.get_by_id(role_id)
        if not role:
            raise LookupError("Rol no encontrado")

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("El nombre del rol es obligatorio")

        role_with_same_name = self.repository.get_by_name(normalized_name)
        if role_with_same_name and role_with_same_name.id != role_id:
            raise ValueError("Ya existe un rol con ese nombre")

        role.name = normalized_name
        role.description = description
        role.permissions = sorted(set(permission.strip() for permission in permissions if permission.strip()))
        role.is_active = is_active
        return self.repository.update(role)

    def delete_role(self, role_id: int) -> None:
        if not self.repository.get_by_id(role_id):
            raise LookupError("Rol no encontrado")
        self.repository.delete(role_id)
