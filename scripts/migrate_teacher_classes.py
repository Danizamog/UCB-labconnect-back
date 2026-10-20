"""Migracion acotada e idempotente de clases docentes y permisos (2026-10-20)."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from migrate_security_rbac import PocketBase, ROOT, field

TEACHER_ONLY = {
    "gestionar_clases_propias", "solicitar_recursos_clase", "gestionar_tutorias_propias",
    "gestionar_asistencia_tutorias", "gestionar_observaciones_tutorias",
}
OSI_ONLY = {
    "consultar_auditoria_seguridad", "consultar_eventos_autenticacion", "consultar_sesiones_usuarios",
    "consultar_incidentes_seguridad", "revisar_accesos_rbac", "exportar_reportes_seguridad",
}


def desired_permissions(role: dict) -> list[str]:
    permissions = list(role.get("permisos") or [])
    name = role.get("name")
    if name == "Administrador":
        permissions = [p for p in permissions if p not in TEACHER_ONLY | OSI_ONLY]
        permissions = list(dict.fromkeys([*permissions, "aprobar_clases", "aprobar_tutorias"]))
    elif name == "Docente":
        permissions = list(dict.fromkeys([*permissions, "gestionar_clases_propias"]))
    if name != "Administrador":
        permissions = [p for p in permissions if p != "aprobar_clases"]
    return permissions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Inspeccion de solo lectura")
    options = parser.parse_args()
    pb = PocketBase()
    collection = pb.collection("lab_schedule")
    if not collection:
        raise RuntimeError("No existe la coleccion lab_schedule")
    roles = pb.records("role")
    schedules = pb.records("lab_schedule")
    changes = [role for role in roles if desired_permissions(role) != role.get("permisos", [])]
    if options.check:
        print(json.dumps({"clases": len(schedules), "roles_por_actualizar": [r["name"] for r in changes],
                          "campos_existentes": [f["name"] for f in collection["fields"]]}, ensure_ascii=False))
        return
    backup_dir = ROOT / ".backups"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / f"teacher_classes_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.json"
    backup_path.write_text(json.dumps({"collection": collection, "roles": roles, "schedules": schedules}, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = list(collection["fields"])
    names = {f["name"] for f in fields}
    additions = [field("approval_status", "text", max=20), field("approval_reason", "text", max=1000),
                 field("approved_by", "text", max=40), field("approved_at", "date")]
    fields.extend(f for f in additions if f["name"] not in names)
    pb.request("PATCH", f"/api/collections/{collection['id']}", {"fields": fields})
    migrated = 0
    for item in schedules:
        if not item.get("approval_status"):
            # Los horarios existentes se conservan aprobados, con su actividad original.
            pb.request("PATCH", f"/api/collections/lab_schedule/records/{item['id']}", {"approval_status": "approved"})
            migrated += 1
    for role in changes:
        pb.request("PATCH", f"/api/collections/role/records/{role['id']}", {"permisos": desired_permissions(role)})
    # Verificacion sin exponer datos de usuarios o credenciales.
    for role in pb.records("role"):
        if desired_permissions(role) != role.get("permisos", []):
            raise RuntimeError("No se pudo verificar la matriz actualizada")
    print(json.dumps({"backup": str(backup_path), "clases_migradas": migrated,
                      "roles_actualizados": [r["name"] for r in changes]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
