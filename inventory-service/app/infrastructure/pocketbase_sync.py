from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal
from app.infrastructure.pocketbase_client import PocketBaseClient
from app.models.asset import Asset
from app.models.asset_status_log import AssetStatusLog
from app.models.loan_record import LoanRecord
from app.models.stock_item import StockItem
from app.models.stock_movement import StockMovement


inventory_pocketbase_client = PocketBaseClient(
    base_url=settings.pocketbase_url,
    auth_token=settings.pocketbase_auth_token,
    auth_identity=settings.pocketbase_auth_identity,
    auth_password=settings.pocketbase_auth_password,
    auth_collection=settings.pocketbase_auth_collection,
    timeout_seconds=settings.pocketbase_timeout_seconds,
)

logger = logging.getLogger("inventory.pocketbase_sync")


INVENTORY_COLLECTIONS: dict[str, list[dict[str, Any]]] = {
    settings.pb_assets_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "name", "type": "text", "required": True, "max": 120},
        {"name": "category", "type": "text", "required": True, "max": 80},
        {"name": "location", "type": "text", "required": True, "max": 160},
        {"name": "description", "type": "text", "required": False, "max": 2000},
        {"name": "serial_number", "type": "text", "required": False, "max": 120},
        {"name": "laboratory_id", "type": "number", "required": False},
        {"name": "status", "type": "text", "required": True, "max": 30},
        {"name": "created_at", "type": "date", "required": False},
        {"name": "updated_at", "type": "date", "required": False},
        {"name": "status_updated_at", "type": "date", "required": False},
        {"name": "status_updated_by", "type": "text", "required": False, "max": 160},
    ],
    settings.pb_stock_items_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "name", "type": "text", "required": True, "max": 120},
        {"name": "category", "type": "text", "required": True, "max": 80},
        {"name": "unit", "type": "text", "required": True, "max": 50},
        {"name": "quantity_available", "type": "number", "required": False},
        {"name": "minimum_stock", "type": "number", "required": False},
        {"name": "laboratory_id", "type": "number", "required": False},
        {"name": "description", "type": "text", "required": False, "max": 2000},
        {"name": "created_at", "type": "date", "required": False},
    ],
    settings.pb_stock_movements_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "stock_item_id", "type": "number", "required": True},
        {"name": "movement_type", "type": "text", "required": True, "max": 40},
        {"name": "quantity_change", "type": "number", "required": False},
        {"name": "quantity_before", "type": "number", "required": False},
        {"name": "quantity_after", "type": "number", "required": False},
        {"name": "reference_type", "type": "text", "required": False, "max": 40},
        {"name": "reference_id", "type": "number", "required": False},
        {"name": "performed_by", "type": "text", "required": True, "max": 160},
        {"name": "notes", "type": "text", "required": False, "max": 2000},
        {"name": "created_at", "type": "date", "required": False},
    ],
    settings.pb_loan_records_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "loan_type", "type": "text", "required": True, "max": 20},
        {"name": "source_type", "type": "text", "required": True, "max": 30},
        {"name": "practice_request_id", "type": "number", "required": False},
        {"name": "asset_id", "type": "number", "required": False},
        {"name": "stock_item_id", "type": "number", "required": False},
        {"name": "laboratory_id", "type": "number", "required": False},
        {"name": "item_name", "type": "text", "required": True, "max": 120},
        {"name": "item_category", "type": "text", "required": False, "max": 80},
        {"name": "borrower_name", "type": "text", "required": True, "max": 120},
        {"name": "borrower_email", "type": "text", "required": True, "max": 180},
        {"name": "borrower_role", "type": "text", "required": True, "max": 80},
        {"name": "purpose", "type": "text", "required": True, "max": 4000},
        {"name": "quantity", "type": "number", "required": False},
        {"name": "status", "type": "text", "required": True, "max": 20},
        {"name": "return_condition", "type": "text", "required": False, "max": 30},
        {"name": "notes", "type": "text", "required": False, "max": 4000},
        {"name": "return_notes", "type": "text", "required": False, "max": 4000},
        {"name": "incident_notes", "type": "text", "required": False, "max": 4000},
        {"name": "approved_by", "type": "text", "required": False, "max": 120},
        {"name": "returned_by", "type": "text", "required": False, "max": 120},
        {"name": "loaned_at", "type": "date", "required": False},
        {"name": "due_at", "type": "date", "required": True},
        {"name": "returned_at", "type": "date", "required": False},
    ],
    settings.pb_asset_status_logs_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "asset_id", "type": "number", "required": True},
        {"name": "previous_status", "type": "text", "required": False, "max": 30},
        {"name": "next_status", "type": "text", "required": True, "max": 30},
        {"name": "changed_by", "type": "text", "required": True, "max": 160},
        {"name": "changed_at", "type": "date", "required": False},
        {"name": "notes", "type": "text", "required": False, "max": 2000},
    ],
}


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    normalized = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _sort_key(record: dict[str, Any]) -> tuple[int, int]:
    source_id = record.get("source_id")
    if source_id is None:
        return (1, 0)
    try:
        return (0, int(source_id))
    except (TypeError, ValueError):
        return (1, 0)


def ensure_inventory_pocketbase_collections() -> None:
    if not inventory_pocketbase_client.enabled:
        return
    for collection_name, fields in INVENTORY_COLLECTIONS.items():
        inventory_pocketbase_client.ensure_collection(collection_name, fields)


def _asset_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(Asset).order_by(Asset.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "name": row.name,
                "category": row.category,
                "location": row.location,
                "description": row.description,
                "serial_number": row.serial_number,
                "laboratory_id": row.laboratory_id,
                "status": row.status,
                "created_at": _isoformat(row.created_at),
                "updated_at": _isoformat(row.updated_at),
                "status_updated_at": _isoformat(row.status_updated_at),
                "status_updated_by": row.status_updated_by,
            }
            for row in rows
        ]


def _stock_item_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(StockItem).order_by(StockItem.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "name": row.name,
                "category": row.category,
                "unit": row.unit,
                "quantity_available": row.quantity_available,
                "minimum_stock": row.minimum_stock,
                "laboratory_id": row.laboratory_id,
                "description": row.description,
                "created_at": _isoformat(row.created_at),
            }
            for row in rows
        ]


def _stock_movement_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(StockMovement).order_by(StockMovement.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "stock_item_id": row.stock_item_id,
                "movement_type": row.movement_type,
                "quantity_change": row.quantity_change,
                "quantity_before": row.quantity_before,
                "quantity_after": row.quantity_after,
                "reference_type": row.reference_type,
                "reference_id": row.reference_id,
                "performed_by": row.performed_by,
                "notes": row.notes,
                "created_at": _isoformat(row.created_at),
            }
            for row in rows
        ]


def _loan_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(LoanRecord).order_by(LoanRecord.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "loan_type": row.loan_type,
                "source_type": row.source_type,
                "practice_request_id": row.practice_request_id,
                "asset_id": row.asset_id,
                "stock_item_id": row.stock_item_id,
                "laboratory_id": row.laboratory_id,
                "item_name": row.item_name,
                "item_category": row.item_category,
                "borrower_name": row.borrower_name,
                "borrower_email": row.borrower_email,
                "borrower_role": row.borrower_role,
                "purpose": row.purpose,
                "quantity": row.quantity,
                "status": row.status,
                "return_condition": row.return_condition,
                "notes": row.notes,
                "return_notes": row.return_notes,
                "incident_notes": row.incident_notes,
                "approved_by": row.approved_by,
                "returned_by": row.returned_by,
                "loaned_at": _isoformat(row.loaned_at),
                "due_at": _isoformat(row.due_at),
                "returned_at": _isoformat(row.returned_at),
            }
            for row in rows
        ]


def _asset_status_log_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(AssetStatusLog).order_by(AssetStatusLog.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "asset_id": row.asset_id,
                "previous_status": row.previous_status,
                "next_status": row.next_status,
                "changed_by": row.changed_by,
                "changed_at": _isoformat(row.changed_at),
                "notes": row.notes,
            }
            for row in rows
        ]


def sync_inventory_to_pocketbase() -> None:
    if not inventory_pocketbase_client.enabled:
        return

    ensure_inventory_pocketbase_collections()
    sync_plan = [
        (settings.pb_assets_collection, _asset_records_from_db()),
        (settings.pb_stock_items_collection, _stock_item_records_from_db()),
        (settings.pb_stock_movements_collection, _stock_movement_records_from_db()),
        (settings.pb_loan_records_collection, _loan_records_from_db()),
        (settings.pb_asset_status_logs_collection, _asset_status_log_records_from_db()),
    ]

    for collection_name, records in sync_plan:
        try:
            inventory_pocketbase_client.replace_collection_records(collection_name, records)
        except Exception as exc:
            logger.warning("No se pudo sincronizar la coleccion %s con PocketBase: %s", collection_name, exc)


def _inventory_has_remote_data() -> bool:
    if not inventory_pocketbase_client.enabled:
        return False
    tracked = [
        settings.pb_assets_collection,
        settings.pb_stock_items_collection,
        settings.pb_loan_records_collection,
        settings.pb_stock_movements_collection,
        settings.pb_asset_status_logs_collection,
    ]
    for collection_name in tracked:
        if inventory_pocketbase_client.list_records(collection_name):
            return True
    return False


def _inventory_remote_total_records() -> int:
    tracked = [
        settings.pb_assets_collection,
        settings.pb_stock_items_collection,
        settings.pb_loan_records_collection,
        settings.pb_stock_movements_collection,
        settings.pb_asset_status_logs_collection,
    ]
    return sum(len(inventory_pocketbase_client.list_records(collection_name)) for collection_name in tracked)


def _inventory_local_total_records() -> int:
    with SessionLocal() as db:
        return (
            db.query(Asset).count()
            + db.query(StockItem).count()
            + db.query(LoanRecord).count()
            + db.query(StockMovement).count()
            + db.query(AssetStatusLog).count()
        )


def _purge_inventory_local_data() -> None:
    with SessionLocal() as db:
        db.query(AssetStatusLog).delete()
        db.query(LoanRecord).delete()
        db.query(StockMovement).delete()
        db.query(StockItem).delete()
        db.query(Asset).delete()
        db.commit()
        try:
            db.execute(text("DELETE FROM sqlite_sequence"))
            db.commit()
        except Exception:
            db.rollback()


def import_inventory_from_pocketbase() -> None:
    if not inventory_pocketbase_client.enabled:
        return

    assets = sorted(inventory_pocketbase_client.list_records(settings.pb_assets_collection), key=_sort_key)
    stock_items = sorted(inventory_pocketbase_client.list_records(settings.pb_stock_items_collection), key=_sort_key)
    stock_movements = sorted(
        inventory_pocketbase_client.list_records(settings.pb_stock_movements_collection),
        key=_sort_key,
    )
    loan_records = sorted(inventory_pocketbase_client.list_records(settings.pb_loan_records_collection), key=_sort_key)
    asset_status_logs = sorted(
        inventory_pocketbase_client.list_records(settings.pb_asset_status_logs_collection),
        key=_sort_key,
    )

    _purge_inventory_local_data()

    with SessionLocal() as db:
        for record in assets:
            db.add(
                Asset(
                    id=int(record["source_id"]),
                    name=record.get("name") or "",
                    category=record.get("category") or "",
                    location=record.get("location") or "Ubicacion pendiente",
                    description=record.get("description"),
                    serial_number=record.get("serial_number"),
                    laboratory_id=int(record["laboratory_id"]) if record.get("laboratory_id") is not None else None,
                    status=record.get("status") or "available",
                    created_at=_parse_datetime(record.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_datetime(record.get("updated_at")) or datetime.utcnow(),
                    status_updated_at=_parse_datetime(record.get("status_updated_at")),
                    status_updated_by=record.get("status_updated_by"),
                )
            )
        db.commit()

        for record in stock_items:
            db.add(
                StockItem(
                    id=int(record["source_id"]),
                    name=record.get("name") or "",
                    category=record.get("category") or "",
                    unit=record.get("unit") or "unidad",
                    quantity_available=int(record.get("quantity_available") or 0),
                    minimum_stock=int(record.get("minimum_stock") or 0),
                    laboratory_id=int(record["laboratory_id"]) if record.get("laboratory_id") is not None else None,
                    description=record.get("description"),
                    created_at=_parse_datetime(record.get("created_at")) or datetime.utcnow(),
                )
            )
        db.commit()

        for record in stock_movements:
            db.add(
                StockMovement(
                    id=int(record["source_id"]),
                    stock_item_id=int(record["stock_item_id"]),
                    movement_type=record.get("movement_type") or "adjustment",
                    quantity_change=int(record.get("quantity_change") or 0),
                    quantity_before=int(record.get("quantity_before") or 0),
                    quantity_after=int(record.get("quantity_after") or 0),
                    reference_type=record.get("reference_type"),
                    reference_id=int(record["reference_id"]) if record.get("reference_id") is not None else None,
                    performed_by=record.get("performed_by") or "system",
                    notes=record.get("notes"),
                    created_at=_parse_datetime(record.get("created_at")) or datetime.utcnow(),
                )
            )
        db.commit()

        for record in loan_records:
            db.add(
                LoanRecord(
                    id=int(record["source_id"]),
                    loan_type=record.get("loan_type") or "material",
                    source_type=record.get("source_type") or "manual",
                    practice_request_id=int(record["practice_request_id"]) if record.get("practice_request_id") is not None else None,
                    asset_id=int(record["asset_id"]) if record.get("asset_id") is not None else None,
                    stock_item_id=int(record["stock_item_id"]) if record.get("stock_item_id") is not None else None,
                    laboratory_id=int(record["laboratory_id"]) if record.get("laboratory_id") is not None else None,
                    item_name=record.get("item_name") or "",
                    item_category=record.get("item_category"),
                    borrower_name=record.get("borrower_name") or "",
                    borrower_email=record.get("borrower_email") or "",
                    borrower_role=record.get("borrower_role") or "Usuario",
                    purpose=record.get("purpose") or "",
                    quantity=int(record.get("quantity") or 1),
                    status=record.get("status") or "active",
                    return_condition=record.get("return_condition"),
                    notes=record.get("notes"),
                    return_notes=record.get("return_notes"),
                    incident_notes=record.get("incident_notes"),
                    approved_by=record.get("approved_by"),
                    returned_by=record.get("returned_by"),
                    loaned_at=_parse_datetime(record.get("loaned_at")) or datetime.utcnow(),
                    due_at=_parse_datetime(record.get("due_at")) or datetime.utcnow(),
                    returned_at=_parse_datetime(record.get("returned_at")),
                )
            )
        db.commit()

        for record in asset_status_logs:
            db.add(
                AssetStatusLog(
                    id=int(record["source_id"]),
                    asset_id=int(record["asset_id"]),
                    previous_status=record.get("previous_status"),
                    next_status=record.get("next_status") or "available",
                    changed_by=record.get("changed_by") or "system",
                    changed_at=_parse_datetime(record.get("changed_at")) or datetime.utcnow(),
                    notes=record.get("notes"),
                )
            )
        db.commit()


def initialize_inventory_pocketbase_sync() -> None:
    if not inventory_pocketbase_client.enabled:
        return
    ensure_inventory_pocketbase_collections()
    try:
        if _inventory_has_remote_data() and _inventory_remote_total_records() >= _inventory_local_total_records():
            import_inventory_from_pocketbase()
        else:
            sync_inventory_to_pocketbase()
    except Exception as exc:
        logger.warning("PocketBase no pudo inicializar inventario; se continua con el cache local: %s", exc)
