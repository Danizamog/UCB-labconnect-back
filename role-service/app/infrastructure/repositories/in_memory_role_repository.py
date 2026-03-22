from app.domain.entities.role import Role


class InMemoryRoleRepository:
    def __init__(self) -> None:
        self._roles: dict[int, Role] = {}
        self._id_counter = 1

    def list_all(self) -> list[Role]:
        return sorted(self._roles.values(), key=lambda role: role.id)

    def get_by_id(self, role_id: int) -> Role | None:
        return self._roles.get(role_id)

    def get_by_name(self, name: str) -> Role | None:
        normalized = name.strip().lower()
        for role in self._roles.values():
            if role.name.lower() == normalized:
                return role
        return None

    def create(self, role: Role) -> Role:
        role.id = self._id_counter
        self._roles[self._id_counter] = role
        self._id_counter += 1
        return role

    def update(self, role: Role) -> Role:
        self._roles[role.id] = role
        return role

    def delete(self, role_id: int) -> None:
        self._roles.pop(role_id, None)
