"""Historial RBAC cerrado y cambios transaccionales; no cambia roles ni usuarios."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from migrate_dual_auth import EnvironmentPocketBase, ROOT
from migrate_security_rbac import field, audit_fields

COLLECTION = "role_change_history"
FIELDS = audit_fields([
    field("actor_id", "text", required=True, max=40),
    field("actor_email", "email", required=True), field("actor_role", "text", max=100),
    field("action", "text", required=True, max=60), field("role_id", "text", max=40),
    field("role_name", "text", max=100), field("target_user_id", "text", max=40),
    field("target_email", "email"), field("before", "json"), field("after", "json"),
    field("reason", "text", required=True, min=5, max=500), field("result", "text", required=True, max=30),
])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--apply", action="store_true")
    options = parser.parse_args()
    pb = EnvironmentPocketBase(options.env_file.resolve())
    collection = pb.collection(COLLECTION)
    settings = pb.request("GET", "/api/settings")
    batch = settings.get("batch") or {}
    rules = {name: None for name in ("listRule", "viewRule", "createRule", "updateRule", "deleteRule")}
    missing = [item for item in FIELDS if not collection or not any(current["name"] == item["name"] for current in collection["fields"])]
    summary = {"crear_historial": not bool(collection), "campos_pendientes": [item["name"] for item in missing],
               "cerrar_reglas": bool(collection and any(collection.get(key) is not None for key in rules)),
               "habilitar_batch": not bool(batch.get("enabled")), "usuarios_modificados": 0, "roles_modificados": 0}
    if not options.apply:
        print(json.dumps(summary)); return
    backup = ROOT / ".backups" / ("role_history_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + ".json")
    backup.parent.mkdir(exist_ok=True)
    backup.write_text(json.dumps({"collection": collection, "batch": batch,
                                 "roles": pb.records(pb.roles_collection)}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not collection:
        pb.request("POST", "/api/collections", {"name": COLLECTION, "type": "base", "fields": FIELDS, **rules,
                   "indexes": [f"CREATE INDEX idx_role_history_role ON {COLLECTION} (role_id, created)",
                               f"CREATE INDEX idx_role_history_actor ON {COLLECTION} (actor_id, created)"]})
    elif missing or summary["cerrar_reglas"]:
        pb.request("PATCH", f"/api/collections/{collection['id']}", {"fields": [*collection["fields"], *missing], **rules})
    if not batch.get("enabled"):
        pb.request("PATCH", "/api/settings", {"batch": {**batch, "enabled": True, "maxRequests": 10, "timeout": 3, "maxBodySize": 262144}})
    verified = pb.collection(COLLECTION)
    assert verified and all(verified.get(key) is None for key in rules)
    assert pb.request("GET", "/api/settings")["batch"]["enabled"]
    summary.update(aplicado=True, respaldo=str(backup))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
