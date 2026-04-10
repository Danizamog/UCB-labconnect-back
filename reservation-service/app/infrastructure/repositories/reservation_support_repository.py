from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient

RESOURCE_NOTES_PREFIX = "[[LABCONNECT_RESOURCES]]"
_OPERATIONS_PERMISSIONS = {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"}


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_reservation_resource_metadata(notes: str | None) -> dict:
    raw_notes = str(notes or "").strip()
    empty = {"assets": [], "materials": [], "user_notes": raw_notes}
    if not raw_notes.startswith(RESOURCE_NOTES_PREFIX):
        return empty

    payload = raw_notes[len(RESOURCE_NOTES_PREFIX) :].strip()
    if not payload:
        return {"assets": [], "materials": [], "user_notes": ""}

    candidates = [payload]
    if "\n" in payload:
        first_line, _, remainder = payload.partition("\n")
        candidates.insert(0, first_line.strip())
        if remainder.strip():
            candidates.append(remainder.strip())

    parsed: dict | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            parsed = decoded
            break

    if parsed is None:
        return empty

    assets: list[dict] = []
    for asset in parsed.get("assets", []):
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("id") or "").strip()
        if not asset_id:
            continue
        assets.append(
            {
                "id": asset_id,
                "name": str(asset.get("name") or "").strip(),
                "serial_number": str(asset.get("serial_number") or "").strip(),
            }
        )

    materials: list[dict] = []
    for material in parsed.get("materials", []):
        if not isinstance(material, dict):
            continue
        material_id = str(material.get("id") or "").strip()
        quantity = _safe_int(material.get("quantity"))
        if not material_id or quantity <= 0:
            continue
        materials.append(
            {
                "id": material_id,
                "name": str(material.get("name") or "").strip(),
                "quantity": quantity,
                "unit": str(material.get("unit") or "").strip(),
            }
        )

    return {
        "assets": assets,
        "materials": materials,
        "user_notes": str(parsed.get("user_notes") or "").strip(),
    }


class ReservationSupportRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._users_base = f"/api/collections/{settings.pb_users_collection}/records"
        self._assets_base = f"/api/collections/{settings.pb_asset_collection}/records"
        self._stock_items_base = f"/api/collections/{settings.pb_stock_item_collection}/records"
        self._labs_base = f"/api/collections/{settings.pb_laboratory_collection}/records"

    def _get_record(self, base_path: str, record_id: str, *, expand: str = "") -> dict | None:
        normalized_id = str(record_id or "").strip()
        if not normalized_id:
            return None
        try:
            data = self._client.request(
                "GET",
                f"{base_path}/{normalized_id}",
                params={"expand": expand} if expand else None,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return data if isinstance(data, dict) else None

    def _patch_record(self, base_path: str, record_id: str, payload: dict) -> dict | None:
        data = self._client.request("PATCH", f"{base_path}/{record_id}", payload=payload)
        return data if isinstance(data, dict) else None

    def get_laboratory_name(self, laboratory_id: str) -> str:
        record = self._get_record(self._labs_base, laboratory_id)
        if not isinstance(record, dict):
            return ""
        return str(record.get("name") or "").strip()

    def list_operations_recipients(self) -> list[dict]:
        items: list[dict] = []
        page = 1

        while True:
            data = self._client.request(
                "GET",
                self._users_base,
                params={
                    "page": page,
                    "perPage": 200,
                    "expand": "role",
                    "sort": "-created",
                },
            )
            if not isinstance(data, dict):
                break

            batch = data.get("items", [])
            if not isinstance(batch, list) or not batch:
                break

            items.extend(item for item in batch if isinstance(item, dict))
            total_pages = int(data.get("totalPages", page))
            if page >= total_pages:
                break
            page += 1

        recipients: list[dict] = []
        seen_ids: set[str] = set()
        for item in items:
            user_id = str(item.get("id") or "").strip()
            email = str(item.get("email") or "").strip().lower()
            if not user_id or not bool(item.get("is_active", True)) or user_id in seen_ids:
                continue

            profile_type = str(item.get("profile_type") or "").strip().lower()
            expand = item.get("expand") if isinstance(item.get("expand"), dict) else {}
            role = expand.get("role") if isinstance(expand, dict) and isinstance(expand.get("role"), dict) else {}
            role_name = str(role.get("name") or role.get("nombre") or "").strip().lower()
            raw_permissions = []
            if isinstance(role, dict):
                raw_permissions = role.get("permissions") or role.get("permisos") or []
                if not isinstance(raw_permissions, list):
                    raw_permissions = []

            permissions = {
                str(permission).strip()
                for permission in raw_permissions
                if str(permission).strip()
            }

            should_include = (
                email == settings.default_admin_username
                or profile_type == "lab_manager"
                or "encargado" in role_name
                or bool(permissions.intersection(_OPERATIONS_PERMISSIONS))
            )
            if not should_include:
                continue

            seen_ids.add(user_id)
            recipients.append(
                {
                    "id": user_id,
                    "email": email,
                    "name": str(item.get("name") or email or "Operaciones").strip(),
                }
            )

        return recipients

    def reserve_resources(self, metadata: dict, *, actor_name: str) -> dict:
        reserved_assets: list[str] = []
        reserved_materials: list[dict] = []
        asset_requests = metadata.get("assets", []) if isinstance(metadata, dict) else []
        material_requests = metadata.get("materials", []) if isinstance(metadata, dict) else []

        try:
            for asset in asset_requests:
                asset_id = str((asset or {}).get("id") or "").strip()
                if not asset_id:
                    continue

                record = self._get_record(self._assets_base, asset_id)
                if not isinstance(record, dict):
                    raise ValueError("Uno de los equipos seleccionados ya no existe")

                current_status = str(record.get("status") or "available").strip().lower()
                if current_status != "available":
                    asset_name = str(record.get("name") or "Equipo").strip()
                    raise ValueError(f"El equipo '{asset_name}' ya no esta disponible para reservar")

                reserved_assets.append(asset_id)

            for material in material_requests:
                material_id = str((material or {}).get("id") or "").strip()
                quantity = _safe_int((material or {}).get("quantity"))
                if not material_id or quantity <= 0:
                    continue

                record = self._get_record(self._stock_items_base, material_id)
                if not isinstance(record, dict):
                    raise ValueError("Uno de los materiales seleccionados ya no existe")

                current_quantity = _safe_int(record.get("quantity_available"))
                if current_quantity < quantity:
                    material_name = str(record.get("name") or "Material").strip()
                    raise ValueError(
                        f"El material '{material_name}' ya no tiene stock suficiente para la cantidad solicitada"
                    )

                self._patch_record(
                    self._stock_items_base,
                    material_id,
                    {"quantity_available": current_quantity - quantity},
                )
                reserved_materials.append({"id": material_id, "quantity": quantity})
        except Exception:
            self.release_resources(
                {"assets": [{"id": asset_id} for asset_id in reserved_assets], "materials": reserved_materials},
                actor_name=actor_name,
                restore_materials=True,
            )
            raise

        return {"assets": reserved_assets, "materials": reserved_materials}

    def release_resources(self, metadata: dict, *, actor_name: str, restore_materials: bool) -> None:
        asset_requests = metadata.get("assets", []) if isinstance(metadata, dict) else []
        material_requests = metadata.get("materials", []) if isinstance(metadata, dict) else []

        for asset in asset_requests:
            asset_id = str((asset or {}).get("id") or "").strip()
            if not asset_id:
                continue

        if not restore_materials:
            return

        for material in material_requests:
            material_id = str((material or {}).get("id") or "").strip()
            quantity = _safe_int((material or {}).get("quantity"))
            if not material_id or quantity <= 0:
                continue

            record = self._get_record(self._stock_items_base, material_id)
            if not isinstance(record, dict):
                continue

            current_quantity = _safe_int(record.get("quantity_available"))
            self._patch_record(
                self._stock_items_base,
                material_id,
                {"quantity_available": current_quantity + quantity},
            )
