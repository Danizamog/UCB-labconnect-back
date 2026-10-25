import secrets
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import string
from typing import Any

from app.domain.entities.role import Role


class InMemoryRoleRepository:
    def __init__(self) -> None:
        self._roles: dict[str, Role] = {}
        self._users: dict[str, dict] = {}
        self._history: list[dict] = []

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

    def list_users_with_roles(self) -> list[dict[str, Any]]:
        result = []
        for stored in self._users.values():
            user = deepcopy(stored)
            role = self._roles.get(user.get("roleId"))
            user["role"] = {"id": role.id, "nombre": role.nombre, "permisos": list(role.permisos)} if role else None
            result.append(user)
        return result

    def assign_user_role(self, user_id: str, role_id: str | None) -> dict[str, Any] | None:
        if user_id not in self._users:
            return None
        self._users[user_id]["roleId"] = role_id
        return next(user for user in self.list_users_with_roles() if user["id"] == user_id)

    def apply_change(self, action, event, *, role=None, user_id="", role_id=None):
        event = deepcopy(event)
        if action == "create":
            result = self.create(role)
            event["role_id"] = role.id
            event["after"]["id"] = role.id
        elif action == "update":
            result = self.update(role)
        elif action == "delete":
            result = self.delete(role.id)
        else:
            result = self.assign_user_role(user_id, role_id)
        self._history.insert(0, {**event, "id": self._generate_id(), "created": datetime.now(timezone.utc).isoformat()})
        return result

    def list_history(self, *, page=1, per_page=25, query="", action="", date_from=None, date_to=None, snapshot_at=None):
        snapshot_at = snapshot_at or datetime.now(timezone.utc)
        if snapshot_at.tzinfo is None:
            snapshot_at = snapshot_at.replace(tzinfo=timezone.utc)
        def local_date(item):
            return datetime.fromisoformat(item["created"].replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=-4))).date()
        items = [deepcopy(item) for item in self._history
                 if datetime.fromisoformat(item["created"].replace("Z", "+00:00")) <= snapshot_at
                 and (not action or item["action"] == action)
                 and (not query or any(query.lower() in str(item.get(key, '')).lower() for key in ("actor_email", "role_name", "target_email", "reason")))
                 and (not date_from or local_date(item) >= date_from)
                 and (not date_to or local_date(item) <= date_to)]
        return {"items": items[(page - 1) * per_page:page * per_page], "page": page,
                "totalItems": len(items), "totalPages": (len(items) + per_page - 1) // per_page, "snapshotAt": snapshot_at.isoformat()}
