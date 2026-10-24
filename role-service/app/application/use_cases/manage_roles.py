from typing import Any

from app.domain.permission_catalog import DEFAULT_ROLE_TEMPLATES
from app.domain.permission_catalog import PERMISSION_CATALOG
from app.domain.permission_catalog import SYSTEM_ROLE_NAMES
from app.domain.permission_catalog import normalize_permissions
from app.domain.entities.role import Role
from app.domain.repositories.role_repository import RoleRepository


PRIVILEGED_ROLE_NAMES = {"Administrador", "Administrador de Accesos", "OSI - Auditor de Seguridad"}
PRIVILEGED_PERMISSIONS = {
    "aprobar_clases",
    "modificar_usuarios", "dar_baja_usuarios", "desbloquear_usuarios",
    "reiniciar_credenciales", "gestionar_roles", "asignar_roles",
    "consultar_auditoria_seguridad", "consultar_eventos_autenticacion", "consultar_sesiones_usuarios",
    "consultar_incidentes_seguridad", "revisar_accesos_rbac", "exportar_reportes_seguridad",
}


class ManageRolesUseCase:
    def __init__(self, repository: RoleRepository):
        self.repository = repository

    def list_roles(self) -> list[Role]:
        return self.repository.list_all()

    def list_permissions_catalog(self) -> list[dict[str, str]]:
        return PERMISSION_CATALOG

    def ensure_default_roles(self) -> None:
        for template in DEFAULT_ROLE_TEMPLATES:
            if self.repository.get_by_nombre(template["nombre"]):
                continue
            self.repository.create(
                Role(
                    id="",
                    nombre=template["nombre"],
                    descripcion=template["descripcion"],
                    permisos=template["permisos"],
                )
            )

    def get_role(self, role_id: str) -> Role:
        role = self.repository.get_by_id(role_id)
        if not role:
            raise LookupError("Rol no encontrado")
        return role

    @staticmethod
    def _ensure_role_permissions_safe(permisos: list[str]) -> None:
        privileged = sorted(set(permisos).intersection(PRIVILEGED_PERMISSIONS))
        if privileged:
            raise ValueError(f"Los permisos privilegiados solo pertenecen a roles controlados: {', '.join(privileged)}")

    def create_role(self, nombre: str, descripcion: str | None, permisos: list[str], actor_permissions: list[str]) -> Role:
        normalized_nombre = nombre.strip()
        if not normalized_nombre:
            raise ValueError("El nombre del rol es obligatorio")

        if self.repository.get_by_nombre(normalized_nombre):
            raise ValueError("Ya existe un rol con ese nombre")

        normalized_permissions = normalize_permissions(permisos)
        self._ensure_role_permissions_safe(normalized_permissions)
        role = Role(
            id="",
            nombre=normalized_nombre,
            descripcion=descripcion,
            permisos=normalized_permissions,
        )
        return self.repository.create(role)

    def update_role(self, role_id: str, nombre: str, descripcion: str | None, permisos: list[str], actor_permissions: list[str]) -> Role:
        role = self.repository.get_by_id(role_id)
        if not role:
            raise LookupError("Rol no encontrado")
        if role.nombre in PRIVILEGED_ROLE_NAMES:
            raise ValueError("Los roles privilegiados se actualizan mediante una migracion controlada")

        normalized_nombre = nombre.strip()
        if not normalized_nombre:
            raise ValueError("El nombre del rol es obligatorio")

        role_with_same_name = self.repository.get_by_nombre(normalized_nombre)
        if role_with_same_name and role_with_same_name.id != role_id:
            raise ValueError("Ya existe un rol con ese nombre")

        role.nombre = normalized_nombre
        role.descripcion = descripcion
        role.permisos = normalize_permissions(permisos)
        self._ensure_role_permissions_safe(role.permisos)
        return self.repository.update(role)

    def delete_role(self, role_id: str) -> None:
        role = self.repository.get_by_id(role_id)
        if not role:
            raise LookupError("Rol no encontrado")
        if role.nombre in SYSTEM_ROLE_NAMES:
            raise ValueError("No se puede eliminar un rol base del sistema")
        self.repository.delete(role_id)

    def list_users_with_roles(self) -> list[dict[str, Any]]:
        return self.repository.list_users_with_roles()

    def assign_user_role(self, user_id: str, role_id: str | None, actor_email: str = "", actor_role: str = "") -> dict[str, Any]:
        users = self.repository.list_users_with_roles()
        access_bootstrap = False
        target = next((user for user in users if user.get("id") == user_id), None)
        if target and actor_email and str(target.get("email") or "").strip().lower() == actor_email.strip().lower():
            raise ValueError("No puedes cambiar tu propio rol")
        target_role_name = (target.get("role") or {}).get("nombre") if target else ""
        if role_id:
            selected_role = self.repository.get_by_id(role_id)
            if not selected_role:
                raise LookupError("Rol no encontrado")
            if selected_role.nombre in PRIVILEGED_ROLE_NAMES:
                access_bootstrap = (
                    selected_role.nombre == "Administrador de Accesos"
                    and actor_role == "Administrador"
                    and target_role_name == "Administrador"
                    and not any((item.get("role") or {}).get("nombre") == "Administrador de Accesos" for item in users)
                )
                osi_assignment = selected_role.nombre == "OSI - Auditor de Seguridad" and actor_role == "Administrador de Accesos" and target_role_name not in PRIVILEGED_ROLE_NAMES
                if not access_bootstrap and not osi_assignment:
                    raise ValueError("La asignacion privilegiada no cumple la separacion de funciones")
        if target_role_name in PRIVILEGED_ROLE_NAMES and not (
            role_id and selected_role.nombre == "Administrador de Accesos" and actor_role == "Administrador" and target_role_name == "Administrador"
        ):
            raise ValueError("Los roles privilegiados no pueden retirarse desde esta operacion")
            if selected_role.nombre in PRIVILEGED_ROLE_NAMES:
                raise ValueError("Los roles privilegiados solo se asignan mediante una migracion controlada")

        user = self.repository.assign_user_role(user_id=user_id, role_id=role_id)
        if not user:
            raise LookupError("Usuario no encontrado")
        if access_bootstrap:
            admin_role = self.repository.get_by_nombre("Administrador")
            admin_template = next(template for template in DEFAULT_ROLE_TEMPLATES if template["nombre"] == "Administrador")
            if admin_role:
                admin_role.descripcion = admin_template["descripcion"]
                admin_role.permisos = list(admin_template["permisos"])
                self.repository.update(admin_role)
        return user
