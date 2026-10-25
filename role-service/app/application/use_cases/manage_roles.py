from dataclasses import asdict
from threading import RLock

from app.domain.permission_catalog import DEFAULT_ROLE_TEMPLATES, PERMISSION_CATALOG, SYSTEM_ROLE_NAMES, normalize_permissions
from app.domain.entities.role import Role
from app.domain.repositories.role_repository import RoleRepository

_role_write_lock = RLock()
ACCESS_PERMISSIONS = {"gestionar_roles", "asignar_roles"}
LOCKED_ADMIN_ROLES = {"Administrador", "Administrador de Accesos"}


class ManageRolesUseCase:
    def __init__(self, repository: RoleRepository):
        self.repository = repository

    def list_roles(self):
        return self.repository.list_all()

    def list_permissions_catalog(self):
        return PERMISSION_CATALOG

    def ensure_default_roles(self):
        for template in DEFAULT_ROLE_TEMPLATES:
            if not self.repository.get_by_nombre(template["nombre"]):
                self.repository.create(Role(id="", **template))

    def get_role(self, role_id):
        role = self.repository.get_by_id(role_id)
        if not role:
            raise LookupError("Rol no encontrado")
        return role

    @staticmethod
    def _event(actor, permission, reason, action, *, role=None, target=None, before=None, after=None):
        if permission not in (actor.get("permissions") or []):
            raise PermissionError("No tienes permisos para realizar esta operacion")
        if not actor.get("user_id") or not actor.get("username"):
            raise PermissionError("No se pudo identificar al responsable del cambio")
        reason = str(reason or "").strip()
        if len(reason) < 5 or len(reason) > 500:
            raise ValueError("Indica un motivo de entre 5 y 500 caracteres")
        return {
            "actor_id": actor["user_id"], "actor_email": actor["username"],
            "actor_role": actor.get("role") or "", "action": action,
            "role_id": role.id if role else "", "role_name": role.nombre if role else "",
            "target_user_id": (target or {}).get("id") or "",
            "target_email": (target or {}).get("email") or "",
            "before": before or {}, "after": after or {}, "reason": reason, "result": "success",
        }

    def _keep_access_manager(self, *, changed_role=None, assignment=None):
        roles = {role.id: set(role.permisos) for role in self.repository.list_all()}
        users = self.repository.list_users_with_roles()
        def available(role_permissions, user_assignment=None):
            return any(user.get("is_active", True)
                       and ACCESS_PERMISSIONS <= role_permissions.get(
                           user_assignment[1] if user_assignment and user["id"] == user_assignment[0]
                           else user.get("roleId"), set()) for user in users)
        had_manager = available(roles)
        if changed_role:
            roles[changed_role.id] = set(changed_role.permisos)
        if had_manager and not available(roles, assignment):
            raise ValueError("Debe permanecer al menos una cuenta activa con gestionar_roles y asignar_roles")

    def create_role(self, nombre, descripcion, permisos, *, actor, reason):
        with _role_write_lock:
            role = Role(id="", nombre=nombre.strip(), descripcion=descripcion, permisos=normalize_permissions(permisos))
            event = self._event(actor, "gestionar_roles", reason, "role.created", role=role, after=asdict(role))
            if not role.nombre:
                raise ValueError("El nombre del rol es obligatorio")
            if self.repository.get_by_nombre(role.nombre):
                raise ValueError("Ya existe un rol con ese nombre")
            return self.repository.apply_change("create", event, role=role)

    def update_role(self, role_id, nombre, descripcion, permisos, *, actor, reason):
        with _role_write_lock:
            previous = self.get_role(role_id)
            if previous.nombre in LOCKED_ADMIN_ROLES:
                raise PermissionError("La configuracion de Administrador y Administrador de Accesos esta protegida y no se modifica desde la aplicacion")
            catalog = {item["value"] for item in PERMISSION_CATALOG}
            inherited = set(previous.permisos) - catalog
            requested = {item.strip() for item in permisos if item.strip()}
            # Conservar permisos legados existentes sin permitir inventar otros nuevos.
            normalized = normalize_permissions(list(requested - inherited)) + sorted(requested & inherited)
            role = Role(id=role_id, nombre=nombre.strip(), descripcion=descripcion, permisos=normalized)
            event = self._event(actor, "gestionar_roles", reason, "role.updated", role=role, before=asdict(previous), after=asdict(role))
            if not role.nombre:
                raise ValueError("El nombre del rol es obligatorio")
            if previous.nombre in SYSTEM_ROLE_NAMES and role.nombre != previous.nombre:
                raise ValueError("El nombre de los perfiles base es estable; puedes editar su descripcion y todos sus permisos")
            duplicate = self.repository.get_by_nombre(role.nombre)
            if duplicate and duplicate.id != role_id:
                raise ValueError("Ya existe un rol con ese nombre")
            self._keep_access_manager(changed_role=role)
            return self.repository.apply_change("update", event, role=role)

    def delete_role(self, role_id, *, actor, reason):
        with _role_write_lock:
            role = self.get_role(role_id)
            event = self._event(actor, "gestionar_roles", reason, "role.deleted", role=role, before=asdict(role))
            if role.nombre in SYSTEM_ROLE_NAMES:
                raise ValueError("No se elimina un perfil base; puedes editar sus permisos o reasignar sus usuarios")
            if any(user.get("roleId") == role_id for user in self.repository.list_users_with_roles()):
                raise ValueError("Reasigna los usuarios de este rol antes de eliminarlo")
            self.repository.apply_change("delete", event, role=role)

    def list_users_with_roles(self):
        return self.repository.list_users_with_roles()

    def assign_user_role(self, user_id, role_id, *, actor, reason):
        with _role_write_lock:
            target = next((user for user in self.repository.list_users_with_roles() if user["id"] == user_id), None)
            if not target:
                raise LookupError("Usuario no encontrado")
            role = self.get_role(role_id) if role_id else None
            previous = target.get("role") or {}
            event = self._event(actor, "asignar_roles", reason, "user.role_assigned" if role else "user.role_removed", role=role, target=target,
                                before={"role_id": target.get("roleId"), "role_name": previous.get("nombre"), "permissions": previous.get("permisos") or []},
                                after={"role_id": role_id, "role_name": role.nombre if role else None, "permissions": role.permisos if role else []})
            if not role:
                event.update(role_id=target.get("roleId") or "", role_name=previous.get("nombre") or "")
            if target.get("roleId") == role_id:
                raise ValueError("El usuario ya tiene esta asignacion")
            self._keep_access_manager(assignment=(user_id, role_id))
            return self.repository.apply_change("assign", event, user_id=user_id, role_id=role_id)

    def list_history(self, **filters):
        return self.repository.list_history(**filters)
