"""Solicitudes de cambio separadas; conserva todas las clases y su estado actual."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from migrate_dual_auth import EnvironmentPocketBase, ROOT
from migrate_security_rbac import field

FIELDS = [field("original_schedule_id", "text", max=40), field("original_snapshot", "json")]
INDEX = "CREATE UNIQUE INDEX idx_schedule_pending_change ON lab_schedule (original_schedule_id) WHERE original_schedule_id != '' AND approval_status = 'pending'"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--apply", action="store_true")
    options = parser.parse_args()
    pb = EnvironmentPocketBase(options.env_file.resolve())
    collection = pb.collection("lab_schedule")
    if not collection:
        raise RuntimeError("No existe lab_schedule")
    missing = [item for item in FIELDS if not any(current["name"] == item["name"] for current in collection["fields"])]
    indexes = collection.get("indexes") or []
    needs_index = not any("idx_schedule_pending_change" in item for item in indexes)
    batch = pb.request("GET", "/api/settings").get("batch") or {}
    summary = {"campos_pendientes": [item["name"] for item in missing], "indice_pendiente": needs_index,
               "habilitar_batch": not bool(batch.get("enabled")), "registros_modificados": 0, "database": pb.base}
    if not options.apply:
        print(json.dumps(summary)); return
    backup = ROOT / ".backups" / ("schedule_changes_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + ".json")
    backup.parent.mkdir(exist_ok=True)
    records = pb.records("lab_schedule")
    backup.write_text(json.dumps({"collection": collection, "batch": batch, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    if missing or needs_index:
        pb.request("PATCH", f"/api/collections/{collection['id']}", {
            "fields": [*collection["fields"], *missing],
            "indexes": [*indexes, *([INDEX] if needs_index else [])],
        })
    if not batch.get("enabled"):
        pb.request("PATCH", "/api/settings", {"batch": {**batch, "enabled": True, "maxRequests": 10, "timeout": 5, "maxBodySize": 262144}})
    verified = pb.collection("lab_schedule")
    assert all(any(current["name"] == item["name"] for current in verified["fields"]) for item in FIELDS)
    assert any("idx_schedule_pending_change" in item for item in verified["indexes"])
    assert pb.request("GET", "/api/settings")["batch"]["enabled"]
    def normalized(rows):
        return {row["id"]: {key: value for key, value in row.items() if key not in {"original_schedule_id", "original_snapshot"}}
                for row in rows}
    assert normalized(records) == normalized(pb.records("lab_schedule")), "El contenido de las clases cambio durante la migracion; revisar el respaldo"
    summary.update(aplicado=True, respaldo=str(backup))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
