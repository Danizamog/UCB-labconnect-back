import secrets
import string

from app.domain.entities.role import Role


class InMemoryRoleRepository:
    def __init__(self) -> None:
        self._roles: dict[str, Role] = {}

    @staticmethod
    def _generate_id() -> str:
        alphabet = string.ascii_lowercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(15))

    def list_all(self) -> list[Role]:
        return sorted(self._roles.values(), key=lambda role: role.id)

    def get_by_id(self, role_id: str) -> Role | None:
        return self._roles.get(role_id)

    def get_by_nombre(self, nombre: str) -> Role | None:
        normalized = nombre.strip().lower()
        for role in self._roles.values():
            if role.nombre.lower() == normalized:
                return role
        return None

    def create(self, role: Role) -> Role:
        role.id = self._generate_id()
        while role.id in self._roles:
            role.id = self._generate_id()
        self._roles[role.id] = role
        return role

    def update(self, role: Role) -> Role:
        self._roles[role.id] = role
        return role

    def delete(self, role_id: str) -> None:
        self._roles.pop(role_id, None)
