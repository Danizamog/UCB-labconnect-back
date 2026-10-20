"""Migracion idempotente de credenciales, RBAC y colecciones de auditoria."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".mcp.json"


ALL_PERMISSIONS = [
    "consultar_usuarios", "consultar_directorio_operativo",
    "crear_usuarios", "modificar_usuarios", "dar_baja_usuarios", "desbloquear_usuarios", "reiniciar_credenciales",
    "consultar_roles", "gestionar_roles", "asignar_roles",
    "gestionar_reservas", "gestionar_reservas_materiales", "gestionar_reglas_reserva",
    "gestionar_estructura_laboratorios", "gestionar_horarios_laboratorio", "gestionar_accesos_laboratorio",
    "gestionar_penalizaciones", "gestionar_inventario", "gestionar_stock", "gestionar_estado_equipos",
    "gestionar_mantenimiento", "registrar_tickets_equipo", "gestionar_prestamos", "gestionar_reactivos_quimicos",
    "gestionar_tutorias_propias", "aprobar_tutorias", "gestionar_asistencia_tutorias",
    "gestionar_clases_propias", "aprobar_clases",
    "gestionar_observaciones_tutorias", "solicitar_recursos_clase", "generar_reportes", "consultar_estadisticas",
    "consultar_auditoria_seguridad", "consultar_eventos_autenticacion", "consultar_sesiones_usuarios",
    "consultar_incidentes_seguridad", "revisar_accesos_rbac", "exportar_reportes_seguridad",
    "gestionar_clases_propias", "solicitar_recursos_clase", "gestionar_tutorias_propias",
    "gestionar_asistencia_tutorias", "gestionar_observaciones_tutorias",
]

ADMIN_OPERATIONAL_PERMISSIONS = [permission for permission in ALL_PERMISSIONS if permission not in {
    "gestionar_usuarios", "gestionar_estado_cuentas", "crear_usuarios", "modificar_usuarios",
    "dar_baja_usuarios", "desbloquear_usuarios", "reiniciar_credenciales", "gestionar_roles", "asignar_roles",
    "iniciar_restablecimiento_credencial", "consultar_auditoria_seguridad",
    "consultar_eventos_autenticacion", "consultar_sesiones_usuarios",
    "consultar_incidentes_seguridad", "revisar_accesos_rbac", "exportar_reportes_seguridad",
}]
for _shared_permission in ("consultar_usuarios", "consultar_roles", "consultar_directorio_operativo"):
    if _shared_permission not in ADMIN_OPERATIONAL_PERMISSIONS:
        ADMIN_OPERATIONAL_PERMISSIONS.append(_shared_permission)

ACCESS_ADMIN_PERMISSIONS = [
    "consultar_usuarios", "consultar_directorio_operativo", "consultar_roles",
    "crear_usuarios", "modificar_usuarios", "dar_baja_usuarios", "desbloquear_usuarios", "reiniciar_credenciales", "gestionar_roles",
    "asignar_roles",
]

ROLE_TEMPLATES = {
    "Administrador": ADMIN_OPERATIONAL_PERMISSIONS,
    "Administrador de Accesos": ACCESS_ADMIN_PERMISSIONS,
    "Encargado de Laboratorio": [
        "consultar_directorio_operativo", "gestionar_reservas",
        "gestionar_accesos_laboratorio", "gestionar_prestamos", "gestionar_reservas_materiales",
        "registrar_tickets_equipo",
    ],
    "Docente": [
        "gestionar_tutorias_propias", "gestionar_asistencia_tutorias",
        "gestionar_observaciones_tutorias", "solicitar_recursos_clase",
        "gestionar_clases_propias",
    ],
    "Estudiante": [],
    "Invitado": [],
    "OSI - Auditor de Seguridad": [
        "consultar_usuarios", "consultar_directorio_operativo", "consultar_roles", "consultar_estadisticas",
        "consultar_auditoria_seguridad", "consultar_eventos_autenticacion",
        "consultar_sesiones_usuarios", "consultar_incidentes_seguridad",
        "revisar_accesos_rbac", "exportar_reportes_seguridad",
    ],
}

ROLE_DESCRIPTIONS = {
    "Administrador": "Operacion general: areas, laboratorios, reservas, inventario, reportes y pronosticos.",
    "Administrador de Accesos": "Gestion de cuentas, roles y credenciales; sin permisos operativos ni auditoria OSI.",
    "Encargado de Laboratorio": "Opera reservas, equipos y materiales de su laboratorio sin crear productos ni cerrar tickets.",
    "Docente": "Tutorias propias y solicitudes de recursos docentes.",
    "Estudiante": "Autoservicio academico sujeto a propiedad.",
    "Invitado": "Solo consulta de cuenta; sin reservas ni tutorias.",
    "OSI - Auditor de Seguridad": "Auditoria de seguridad y consulta administrativa de solo lectura.",
}


def field(name: str, kind: str, **extra: object) -> dict:
    return {"name": name, "type": kind, "required": False, **extra}


def audit_fields(fields: list[dict]) -> list[dict]:
    return [
        *fields,
        {"name": "created", "type": "autodate", "onCreate": True, "onUpdate": False},
        {"name": "updated", "type": "autodate", "onCreate": True, "onUpdate": True},
    ]


SECURITY_COLLECTIONS = {
    "password_history": audit_fields([
        field("user_id", "text", max=40), field("password_hash", "text", max=500),
        field("reason", "text", max=80),
    ]),
    "security_audit_event": audit_fields([
        field("action", "text", max=160), field("actor_id", "text", max=40),
        field("actor_email", "email"), field("target_type", "text", max=80),
        field("target_id", "text", max=40), field("result", "text", max=30),
        field("reason", "text", max=500), field("metadata", "json"),
    ]),
    "auth_session": audit_fields([
        field("user_id", "text", max=40), field("email", "email"), field("jti", "text", max=80),
        field("status", "text", max=30), field("issued_at", "date"), field("expires_at", "date"),
        field("revoked_at", "date"), field("reason", "text", max=300),
    ]),
    "security_incident": audit_fields([
        field("title", "text", max=200), field("description", "text", max=2000),
        field("severity", "text", max=30), field("status", "text", max=30),
        field("responsible", "text", max=120), field("evidence", "json"),
    ]),
    "access_review": audit_fields([
        field("period", "text", max=80), field("user_id", "text", max=40),
        field("role_name", "text", max=120), field("reviewer_id", "text", max=40),
        field("decision", "text", max=80), field("observation", "text", max=1000),
        field("status", "text", max=30),
    ]),
}


class PocketBase:
    def __init__(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["mcpServers"]["pocketbase"]["env"]
        self.base = str(config["PB_URL"]).rstrip("/")
        auth = self.request("POST", "/api/collections/_superusers/auth-with-password", {
            "identity": config["PB_EMAIL"], "password": config["PB_PASSWORD"],
        }, authenticated=False)
        self.token = auth["token"]

    def request(self, method: str, path: str, payload: dict | None = None, *, authenticated: bool = True) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json", "User-Agent": "LabConnect-Migration/1.0"}
        if authenticated:
            headers["Authorization"] = getattr(self, "token", "")
        request = Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"PocketBase {method} {path}: {exc.code} {detail}") from exc

    def collection(self, name: str) -> dict | None:
        try:
            return self.request("GET", f"/api/collections/{name}")
        except RuntimeError as exc:
            if " 404 " in str(exc):
                return None
            raise

    def records(self, collection: str) -> list[dict]:
        result: list[dict] = []
        page = 1
        while True:
            query = urlencode({"page": page, "perPage": 200, "expand": "role"})
            payload = self.request("GET", f"/api/collections/{collection}/records?{query}")
            result.extend(payload.get("items", []))
            if page >= int(payload.get("totalPages", 1)):
                return result
            page += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Aplica la matriz RBAC y respalda PocketBase")
    parser.add_argument("--access-admin-email", help="Cuenta Administrador existente para gestionar cuentas y accesos")
    parser.add_argument("--defer-admin-split", action="store_true", help="Actualiza los demas roles sin reducir Administrador todavia")
    options = parser.parse_args()
    pb = PocketBase()
    all_collections_payload = pb.request("GET", "/api/collections?page=1&perPage=200")
    all_collections = all_collections_payload.get("items", [])
    users_collection = pb.collection("users")
    role_collection = pb.collection("role")
    if not users_collection or not role_collection:
        raise RuntimeError("No se encontraron las colecciones users y role")

    backup = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "collections": all_collections,
        "roles": pb.records("role"),
        "users": pb.records("users"),
    }
    backup_dir = ROOT / ".backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"pocketbase_security_rbac_{stamp}.json"
    backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")

    existing_names = {item["name"] for item in users_collection["fields"]}
    additions = [
        field("profile_type", "text", max=40), field("phone", "text", max=40),
        field("academic_page", "url"), field("faculty", "text", max=160),
        field("career", "text", max=160), field("student_code", "text", max=80),
        field("campus", "text", max=100), field("bio", "text", max=2000),
        field("auth_provider", "text", max=20), field("password_changed_at", "date"),
        field("session_version", "number", onlyInt=True, min=1), field("security_locked", "bool"),
        field("user_code", "text", max=40), field("failed_login_attempts", "number", onlyInt=True, min=0),
        field("locked_at", "date"), field("password_expires_at", "date"), field("must_change_password", "bool"),
    ]
    fields = list(users_collection["fields"])
    for current in fields:
        if current.get("name") == "password":
            current["min"] = 12
    fields.extend(item for item in additions if item["name"] not in existing_names)
    pb.request("PATCH", f"/api/collections/{users_collection['id']}", {
        "fields": fields,
        "indexes": list(users_collection.get("indexes") or []) + ([] if any("idx_users_user_code_unique" in index for index in (users_collection.get("indexes") or [])) else ["CREATE UNIQUE INDEX `idx_users_user_code_unique` ON `users` (`user_code`) WHERE `user_code` != ''"]),
        "authRule": 'auth_provider = "local"',
        "oauth2": {**(users_collection.get("oauth2") or {}), "enabled": False},
        "listRule": "id = @request.auth.id",
        "viewRule": "id = @request.auth.id",
        "createRule": None,
        "updateRule": None,
        "deleteRule": None,
    })
    for user in pb.records("users"):
        updates = {}
        if not str(user.get("user_code") or "").strip():
            updates["user_code"] = f"UCB-{datetime.now(timezone.utc).year}-{str(user.get('id') or '')[:8].upper()}"
        if not user.get("password_expires_at") and str(user.get("auth_provider") or "local") == "local":
            updates["password_expires_at"] = (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=90)).isoformat()
        if updates:
            pb.request("PATCH", f"/api/collections/users/records/{user['id']}", updates)
    role_fields = list(role_collection["fields"])
    for current in role_fields:
        if current.get("name") == "name":
            current["required"] = True
    role_indexes = list(role_collection.get("indexes") or [])
    unique_role_index = "CREATE UNIQUE INDEX `idx_role_name_unique` ON `role` (`name`)"
    if not any("idx_role_name_unique" in index for index in role_indexes):
        role_indexes.append(unique_role_index)
    pb.request("PATCH", f"/api/collections/{role_collection['id']}", {
        "fields": role_fields, "indexes": role_indexes,
        "listRule": "@request.auth.id != ''", "viewRule": "@request.auth.id != ''",
        "createRule": None, "updateRule": None, "deleteRule": None,
    })

    for name, fields_definition in SECURITY_COLLECTIONS.items():
        read_rule = None if name == "password_history" else '@request.auth.role.name = "OSI - Auditor de Seguridad"'
        existing_security_collection = pb.collection(name)
        if existing_security_collection:
            existing_fields = list(existing_security_collection["fields"])
            existing_field_names = {item["name"] for item in existing_fields}
            existing_fields.extend(item for item in fields_definition if item["name"] not in existing_field_names)
            pb.request("PATCH", f"/api/collections/{existing_security_collection['id']}", {
                "fields": existing_fields,
                "listRule": read_rule,
                "viewRule": read_rule,
                "createRule": None, "updateRule": None, "deleteRule": None,
            })
            continue
        pb.request("POST", "/api/collections", {
            "name": name, "type": "base", "fields": fields_definition,
            "listRule": read_rule,
            "viewRule": read_rule,
            "createRule": None, "updateRule": None, "deleteRule": None,
        })

    # Toda escritura funcional pasa por el gateway y los microservicios. Las
    # cuentas de servicio conservan acceso como superusuario.
    protected_names = {"users", "role", *SECURITY_COLLECTIONS.keys()}
    for collection in all_collections:
        if collection.get("system") or collection.get("name") in protected_names:
            continue
        if collection.get("type") not in {"base", "auth"}:
            continue
        pb.request("PATCH", f"/api/collections/{collection['id']}", {
            "createRule": None, "updateRule": None, "deleteRule": None,
        })

    roles = {record.get("name"): record for record in pb.records("role")}
    access_admin_name = "Administrador de Accesos"
    access_admin_payload = {
        "name": access_admin_name,
        "descripcion": ROLE_DESCRIPTIONS[access_admin_name],
        "permisos": ROLE_TEMPLATES[access_admin_name],
    }
    if access_admin_name in roles:
        pb.request("PATCH", f"/api/collections/role/records/{roles[access_admin_name]['id']}", access_admin_payload)
    else:
        pb.request("POST", "/api/collections/role/records", access_admin_payload)
    roles = {record.get("name"): record for record in pb.records("role")}
    access_admin_id = roles[access_admin_name]["id"]
    legacy_superadmin = roles.get("Superadministrador")
    if legacy_superadmin:
        if any(user.get("role") == legacy_superadmin["id"] for user in pb.records("users")):
            raise RuntimeError("Hay una cuenta Superadministrador antigua; revisa su migracion antes de retirar el rol")
        pb.request("DELETE", f"/api/collections/role/records/{legacy_superadmin['id']}")
        roles.pop("Superadministrador")
    bootstrap_email = str(options.access_admin_email or "").strip().lower()
    if bootstrap_email:
        target = next((user for user in backup["users"] if str(user.get("email") or "").strip().lower() == bootstrap_email), None)
        if target is None:
            raise RuntimeError("La cuenta indicada para Administrador de Accesos no existe")
        if target.get("role") not in {roles["Administrador"]["id"], access_admin_id}:
            raise RuntimeError("La cuenta indicada debe tener actualmente el rol Administrador")
        if target.get("role") != access_admin_id:
            pb.request("PATCH", f"/api/collections/users/records/{target['id']}", {"role": access_admin_id})

    if not options.defer_admin_split and not any(user.get("role") == access_admin_id for user in pb.records("users")):
        raise RuntimeError("No se reducira Administrador sin al menos una cuenta Administrador de Accesos. Usa --access-admin-email.")

    for name, permissions in ROLE_TEMPLATES.items():
        if name == access_admin_name or (name == "Administrador" and options.defer_admin_split):
            continue
        payload = {"name": name, "descripcion": ROLE_DESCRIPTIONS[name], "permisos": permissions}
        if name in roles:
            pb.request("PATCH", f"/api/collections/role/records/{roles[name]['id']}", payload)
        else:
            pb.request("POST", "/api/collections/role/records", payload)

    for user in backup["users"]:
        updates = {}
        if not user.get("auth_provider"):
            updates["auth_provider"] = "local"
        if not user.get("session_version"):
            updates["session_version"] = 1
        if updates:
            pb.request("PATCH", f"/api/collections/users/records/{user['id']}", updates)

    print(json.dumps({"backup": str(backup_path), "roles": len(ROLE_TEMPLATES), "collections": list(SECURITY_COLLECTIONS)}))


if __name__ == "__main__":
    main()
