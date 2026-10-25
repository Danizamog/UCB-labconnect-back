"""Retira del Administrador los permisos de Accesos, con respaldo y auditoria atomica."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from migrate_dual_auth import EnvironmentPocketBase, ROOT

LEGACY_IDENTITY_PERMISSIONS = {"gestionar_usuarios", "gestionar_estado_cuentas", "iniciar_restablecimiento_credencial", "crear_usuarios"}


def remaining_permissions(administrator, access_administrator):
    excluded = set(access_administrator.get("permisos") or []) | LEGACY_IDENTITY_PERMISSIONS
    return [value for value in administrator.get("permisos") or [] if value not in excluded]


def snapshot(role, permissions=None):
    return {"id": role["id"], "nombre": role.get("nombre") or role.get("name"),
            "descripcion": role.get("descripcion") or "", "permisos": (role.get("permisos") or []) if permissions is None else permissions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--apply", action="store_true")
    options = parser.parse_args()
    pb = EnvironmentPocketBase(options.env_file.resolve())
    roles = pb.records(pb.roles_collection)
    by_name = {item.get("nombre") or item.get("name"): item for item in roles}
    admin, access = by_name["Administrador"], by_name["Administrador de Accesos"]
    permissions = remaining_permissions(admin, access)
    removed = sorted(set(admin.get("permisos") or []) - set(permissions))
    summary = {"permisos_por_retirar": removed, "permisos_operativos_restantes": len(permissions),
               "coincidencias_con_accesos": len(set(permissions) & set(access.get("permisos") or []))}
    if not options.apply or not removed:
        print(json.dumps(summary, ensure_ascii=False)); return
    if not pb.collection("role_change_history"):
        raise RuntimeError("Primero aplica la migracion de historial de roles")
    if not pb.request("GET", "/api/settings").get("batch", {}).get("enabled"):
        raise RuntimeError("La auditoria requiere las transacciones batch habilitadas")
    # La identidad se obtiene del servidor al renovar la sesion real de superusuario.
    refreshed = pb.request("POST", "/api/collections/_superusers/auth-refresh")
    responsible = refreshed.get("record") or {}
    if not responsible.get("id") or not responsible.get("email"):
        raise RuntimeError("No se pudo verificar al responsable de la migracion")
    pb.token = refreshed["token"]
    assignments = {user['id']: user.get('role') for user in pb.records(pb.users_collection)}
    backup = ROOT / ".backups" / ("admin_operational_scope_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + ".json")
    backup.parent.mkdir(exist_ok=True)
    backup.write_text(json.dumps({"roles": roles, "assignments": assignments}, ensure_ascii=False, indent=2), encoding="utf-8")
    event = {"actor_id": responsible["id"], "actor_email": responsible["email"],
             "actor_role": "Administracion de BD: migracion autorizada", "action": "role.updated",
             "role_id": admin["id"], "role_name": "Administrador", "target_user_id": "", "target_email": "",
             "before": snapshot(admin), "after": snapshot(admin, permissions), "result": "success",
             "reason": "Solicitud del propietario: retirar del Administrador todos los permisos del Administrador de Accesos y las facultades heredadas de gestion de identidad; conservar su operacion de laboratorios."}
    pb.request("POST", "/api/batch", {"requests": [
        {"method": "PATCH", "url": f"/api/collections/{pb.roles_collection}/records/{admin['id']}", "body": {"permisos": permissions}},
        {"method": "POST", "url": "/api/collections/role_change_history/records", "body": event},
    ]})
    verified_roles = pb.records(pb.roles_collection)
    verified = next(item for item in verified_roles if item['id'] == admin['id'])
    assert verified.get('permisos') == permissions
    assert all(item == next(new for new in verified_roles if new['id'] == item['id']) for item in roles if item['id'] != admin['id'])
    assert assignments == {user['id']: user.get('role') for user in pb.records(pb.users_collection)}
    summary.update(aplicado=True, respaldo=str(backup), otros_roles_sin_cambios=True, asignaciones_conservadas=True, auditoria_registrada=True)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
