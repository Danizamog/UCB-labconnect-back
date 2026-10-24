"""Acceso dual: un campo en users; sin tablas nuevas ni cambios de contrasenas."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from migrate_security_rbac import PocketBase, ROOT, field


class EnvironmentPocketBase(PocketBase):
    def __init__(self, env_file: Path):
        config = {}
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip().strip('"').strip("'")
        config.update({key: value for key, value in os.environ.items() if key.startswith("POCKETBASE_") and value})
        required = ("POCKETBASE_URL", "POCKETBASE_AUTH_IDENTITY", "POCKETBASE_AUTH_PASSWORD")
        if any(not config.get(key) for key in required):
            raise RuntimeError("Configura las variables POCKETBASE_URL, POCKETBASE_AUTH_IDENTITY y POCKETBASE_AUTH_PASSWORD en el archivo privado.")
        self.base = config["POCKETBASE_URL"].rstrip("/")
        self.users_collection = config.get("POCKETBASE_USERS_COLLECTION", "users")
        self.roles_collection = config.get("POCKETBASE_ROLES_COLLECTION", config.get("POCKETBASE_ROLE_COLLECTION", "role"))
        auth_collection = config.get("POCKETBASE_AUTH_COLLECTION", "_superusers")
        auth = self.request("POST", f"/api/collections/{auth_collection}/auth-with-password", {
            "identity": config["POCKETBASE_AUTH_IDENTITY"], "password": config["POCKETBASE_AUTH_PASSWORD"],
        }, authenticated=False)
        self.token = auth["token"]


AUTH_RULE = '(auth_provider = "local" || auth_provider = "hybrid") && is_active = true && security_locked = false'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--apply", action="store_true", help="Aplicar con respaldo previo; por defecto solo comprueba")
    options = parser.parse_args()
    pb = EnvironmentPocketBase(options.env_file.resolve())
    collection = pb.collection(pb.users_collection)
    if not collection:
        raise RuntimeError("No se encontro la coleccion de usuarios")
    roles = pb.records(pb.roles_collection)
    users = pb.records(pb.users_collection)
    changed_roles = [role for role in roles if "crear_usuarios" in (role.get("permisos") or [])]
    add_google_sub = not any(item["name"] == "google_sub" for item in collection["fields"])
    index = f"CREATE UNIQUE INDEX `idx_users_google_sub_unique` ON `{pb.users_collection}` (`google_sub`) WHERE `google_sub` != ''"
    indexes = list(collection.get("indexes") or [])
    needs_index = not any("idx_users_google_sub_unique" in item for item in indexes)
    needs_rule = collection.get("authRule") != AUTH_RULE
    summary = {"usuarios": len(users), "campo_google_sub_pendiente": add_google_sub, "indice_pendiente": needs_index,
               "regla_pendiente": needs_rule, "roles_sin_alta_por_actualizar": len(changed_roles), "tablas_nuevas": 0}
    if not options.apply:
        print(json.dumps(summary))
        return
    backup_dir = ROOT / ".backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / f"dual_auth_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.json"
    backup.write_text(json.dumps({"users_collection": collection, "roles": roles, "users": users}, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = list(collection["fields"])
    if add_google_sub:
        fields.append(field("google_sub", "text", max=255))
    if needs_index:
        indexes.append(index)
    if add_google_sub or needs_index or needs_rule:
        pb.request("PATCH", f"/api/collections/{collection['id']}", {"fields": fields, "indexes": indexes, "authRule": AUTH_RULE,
            "createRule": None, "updateRule": None, "deleteRule": None})
    for role in changed_roles:
        pb.request("PATCH", f"/api/collections/{pb.roles_collection}/records/{role['id']}", {
            "permisos": [permission for permission in role["permisos"] if permission != "crear_usuarios"],
        })
    verified = pb.collection(pb.users_collection)
    if verified.get("authRule") != AUTH_RULE or not any(item["name"] == "google_sub" for item in verified["fields"]):
        raise RuntimeError("No se pudo verificar el esquema actualizado")
    summary.update(aplicado=True, respaldo=str(backup))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
