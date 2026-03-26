from __future__ import annotations

from datetime import date, datetime, time
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.db.session import SessionLocal
from app.infrastructure.pocketbase_client import PocketBaseClient
from app.models.area import Area
from app.models.class_session import ClassSession
from app.models.class_tutorial import ClassTutorial
from app.models.laboratory import Laboratory
from app.models.practice_material import PracticeMaterial
from app.models.practice_request import PracticeRequest


reservations_pocketbase_client = PocketBaseClient(
    base_url=settings.pocketbase_url,
    auth_token=settings.pocketbase_auth_token,
    auth_identity=settings.pocketbase_auth_identity,
    auth_password=settings.pocketbase_auth_password,
    auth_collection=settings.pocketbase_auth_collection,
    timeout_seconds=settings.pocketbase_timeout_seconds,
)

logger = logging.getLogger("reservations.pocketbase_sync")


RESERVATIONS_COLLECTIONS: dict[str, list[dict[str, Any]]] = {
    settings.pb_areas_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "name", "type": "text", "required": True, "max": 120},
        {"name": "description", "type": "text", "required": False, "max": 2000},
        {"name": "is_active", "type": "bool", "required": True},
        {"name": "created_at", "type": "date", "required": False},
    ],
    settings.pb_labs_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "name", "type": "text", "required": True, "max": 120},
        {"name": "location", "type": "text", "required": True, "max": 160},
        {"name": "capacity", "type": "number", "required": True},
        {"name": "description", "type": "text", "required": False, "max": 2000},
        {"name": "is_active", "type": "bool", "required": True},
        {"name": "area_id", "type": "number", "required": True},
        {"name": "created_at", "type": "date", "required": False},
        {"name": "updated_at", "type": "date", "required": False},
    ],
    settings.pb_class_sessions_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "laboratory_id", "type": "number", "required": True},
        {"name": "date", "type": "text", "required": True, "max": 20},
        {"name": "start_time", "type": "text", "required": True, "max": 20},
        {"name": "end_time", "type": "text", "required": True, "max": 20},
        {"name": "subject_name", "type": "text", "required": True, "max": 160},
        {"name": "teacher_name", "type": "text", "required": True, "max": 160},
        {"name": "needs_support", "type": "bool", "required": True},
        {"name": "support_topic", "type": "text", "required": False, "max": 255},
        {"name": "notes", "type": "text", "required": False, "max": 2000},
        {"name": "created_at", "type": "date", "required": False},
    ],
    settings.pb_class_tutorials_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "laboratory_id", "type": "number", "required": True},
        {"name": "session_type", "type": "text", "required": True, "max": 24},
        {"name": "date", "type": "text", "required": True, "max": 20},
        {"name": "start_time", "type": "text", "required": True, "max": 20},
        {"name": "end_time", "type": "text", "required": True, "max": 20},
        {"name": "title", "type": "text", "required": True, "max": 160},
        {"name": "facilitator_name", "type": "text", "required": True, "max": 160},
        {"name": "target_group", "type": "text", "required": False, "max": 160},
        {"name": "academic_unit", "type": "text", "required": False, "max": 160},
        {"name": "needs_support", "type": "bool", "required": True},
        {"name": "support_topic", "type": "text", "required": False, "max": 255},
        {"name": "notes", "type": "text", "required": False, "max": 2000},
        {"name": "created_at", "type": "date", "required": False},
        {"name": "updated_at", "type": "date", "required": False},
    ],
    settings.pb_practice_requests_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "user_id", "type": "text", "required": True, "max": 120},
        {"name": "username", "type": "text", "required": True, "max": 255},
        {"name": "subject_name", "type": "text", "required": False, "max": 160},
        {"name": "laboratory_id", "type": "number", "required": True},
        {"name": "date", "type": "text", "required": True, "max": 20},
        {"name": "start_time", "type": "text", "required": True, "max": 20},
        {"name": "end_time", "type": "text", "required": True, "max": 20},
        {"name": "needs_support", "type": "bool", "required": True},
        {"name": "support_topic", "type": "text", "required": False, "max": 255},
        {"name": "notes", "type": "text", "required": True, "max": 4000},
        {"name": "review_comment", "type": "text", "required": False, "max": 4000},
        {"name": "status", "type": "text", "required": True, "max": 32},
        {"name": "created_at", "type": "date", "required": False},
        {"name": "status_updated_at", "type": "date", "required": False},
        {"name": "user_notification_read", "type": "bool", "required": True},
    ],
    settings.pb_practice_materials_collection: [
        {"name": "source_id", "type": "number", "required": True},
        {"name": "practice_request_id", "type": "number", "required": True},
        {"name": "asset_id", "type": "number", "required": True},
        {"name": "material_name", "type": "text", "required": True, "max": 255},
        {"name": "quantity", "type": "number", "required": True},
    ],
}


def _iso_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _iso_time(value: time | None) -> str | None:
    return value.isoformat() if value is not None else None


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


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _parse_time(value: Any) -> time | None:
    if not value:
        return None
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def _sort_key(record: dict[str, Any]) -> tuple[int, int]:
    source_id = record.get("source_id")
    if source_id is None:
        return (1, 0)
    try:
        return (0, int(source_id))
    except (TypeError, ValueError):
        return (1, 0)


def ensure_reservations_pocketbase_collections() -> None:
    if not reservations_pocketbase_client.enabled:
        return
    for collection_name, fields in RESERVATIONS_COLLECTIONS.items():
        reservations_pocketbase_client.ensure_collection(collection_name, fields)


def _area_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(Area).order_by(Area.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "name": row.name,
                "description": row.description,
                "is_active": row.is_active,
                "created_at": _iso_datetime(row.created_at),
            }
            for row in rows
        ]


def _lab_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(Laboratory).order_by(Laboratory.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "name": row.name,
                "location": row.location,
                "capacity": row.capacity,
                "description": row.description,
                "is_active": row.is_active,
                "area_id": row.area_id,
                "created_at": _iso_datetime(row.created_at),
                "updated_at": _iso_datetime(row.updated_at),
            }
            for row in rows
        ]


def _class_session_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(ClassSession).order_by(ClassSession.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "laboratory_id": row.laboratory_id,
                "date": _iso_date(row.date),
                "start_time": _iso_time(row.start_time),
                "end_time": _iso_time(row.end_time),
                "subject_name": row.subject_name,
                "teacher_name": row.teacher_name,
                "needs_support": row.needs_support,
                "support_topic": row.support_topic,
                "notes": row.notes,
                "created_at": _iso_datetime(row.created_at),
            }
            for row in rows
        ]


def _class_tutorial_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(ClassTutorial).order_by(ClassTutorial.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "laboratory_id": row.laboratory_id,
                "session_type": row.session_type,
                "date": _iso_date(row.date),
                "start_time": _iso_time(row.start_time),
                "end_time": _iso_time(row.end_time),
                "title": row.title,
                "facilitator_name": row.facilitator_name,
                "target_group": row.target_group,
                "academic_unit": row.academic_unit,
                "needs_support": row.needs_support,
                "support_topic": row.support_topic,
                "notes": row.notes,
                "created_at": _iso_datetime(row.created_at),
                "updated_at": _iso_datetime(row.updated_at),
            }
            for row in rows
        ]


def _practice_request_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(PracticeRequest).order_by(PracticeRequest.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "user_id": row.user_id,
                "username": row.username,
                "subject_name": row.subject_name,
                "laboratory_id": row.laboratory_id,
                "date": _iso_date(row.date),
                "start_time": _iso_time(row.start_time),
                "end_time": _iso_time(row.end_time),
                "needs_support": row.needs_support,
                "support_topic": row.support_topic,
                "notes": row.notes,
                "review_comment": row.review_comment,
                "status": row.status,
                "created_at": _iso_datetime(row.created_at),
                "status_updated_at": _iso_datetime(row.status_updated_at),
                "user_notification_read": row.user_notification_read,
            }
            for row in rows
        ]


def _practice_material_records_from_db() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(PracticeMaterial).order_by(PracticeMaterial.id.asc()).all()
        return [
            {
                "source_id": row.id,
                "practice_request_id": row.practice_request_id,
                "asset_id": row.asset_id,
                "material_name": row.material_name,
                "quantity": row.quantity,
            }
            for row in rows
        ]


def sync_reservations_to_pocketbase() -> None:
    if not reservations_pocketbase_client.enabled:
        return

    ensure_reservations_pocketbase_collections()
    sync_plan = [
        (settings.pb_areas_collection, _area_records_from_db()),
        (settings.pb_labs_collection, _lab_records_from_db()),
        (settings.pb_class_sessions_collection, _class_session_records_from_db()),
        (settings.pb_class_tutorials_collection, _class_tutorial_records_from_db()),
        (settings.pb_practice_requests_collection, _practice_request_records_from_db()),
        (settings.pb_practice_materials_collection, _practice_material_records_from_db()),
    ]

    for collection_name, records in sync_plan:
        try:
            reservations_pocketbase_client.replace_collection_records(collection_name, records)
        except Exception as exc:
            logger.warning("No se pudo sincronizar la coleccion %s con PocketBase: %s", collection_name, exc)


def _reservations_has_remote_data() -> bool:
    if not reservations_pocketbase_client.enabled:
        return False
    tracked = [
        settings.pb_areas_collection,
        settings.pb_labs_collection,
        settings.pb_class_sessions_collection,
        settings.pb_class_tutorials_collection,
        settings.pb_practice_requests_collection,
        settings.pb_practice_materials_collection,
    ]
    for collection_name in tracked:
        if reservations_pocketbase_client.list_records(collection_name):
            return True
    return False


def _reservations_remote_total_records() -> int:
    tracked = [
        settings.pb_areas_collection,
        settings.pb_labs_collection,
        settings.pb_class_sessions_collection,
        settings.pb_class_tutorials_collection,
        settings.pb_practice_requests_collection,
        settings.pb_practice_materials_collection,
    ]
    return sum(len(reservations_pocketbase_client.list_records(collection_name)) for collection_name in tracked)


def _reservations_local_total_records() -> int:
    with SessionLocal() as db:
        return (
            db.query(Area).count()
            + db.query(Laboratory).count()
            + db.query(ClassSession).count()
            + db.query(ClassTutorial).count()
            + db.query(PracticeRequest).count()
            + db.query(PracticeMaterial).count()
        )


def _purge_reservations_local_data() -> None:
    with SessionLocal() as db:
        db.query(PracticeMaterial).delete()
        db.query(PracticeRequest).delete()
        db.query(ClassTutorial).delete()
        db.query(ClassSession).delete()
        db.query(Laboratory).delete()
        db.query(Area).delete()
        db.commit()
        try:
            db.execute(text("DELETE FROM sqlite_sequence"))
            db.commit()
        except Exception:
            db.rollback()


def import_reservations_from_pocketbase() -> None:
    if not reservations_pocketbase_client.enabled:
        return

    areas = sorted(reservations_pocketbase_client.list_records(settings.pb_areas_collection), key=_sort_key)
    labs = sorted(reservations_pocketbase_client.list_records(settings.pb_labs_collection), key=_sort_key)
    class_sessions = sorted(
        reservations_pocketbase_client.list_records(settings.pb_class_sessions_collection),
        key=_sort_key,
    )
    class_tutorials = sorted(
        reservations_pocketbase_client.list_records(settings.pb_class_tutorials_collection),
        key=_sort_key,
    )
    practice_requests = sorted(
        reservations_pocketbase_client.list_records(settings.pb_practice_requests_collection),
        key=_sort_key,
    )
    practice_materials = sorted(
        reservations_pocketbase_client.list_records(settings.pb_practice_materials_collection),
        key=_sort_key,
    )

    _purge_reservations_local_data()

    with SessionLocal() as db:
        for record in areas:
            db.add(
                Area(
                    id=int(record["source_id"]),
                    name=record.get("name") or "",
                    description=record.get("description"),
                    is_active=bool(record.get("is_active", True)),
                    created_at=_parse_datetime(record.get("created_at")) or datetime.utcnow(),
                )
            )
        db.commit()

        for record in labs:
            db.add(
                Laboratory(
                    id=int(record["source_id"]),
                    name=record.get("name") or "",
                    location=record.get("location") or "",
                    capacity=int(record.get("capacity") or 0),
                    description=record.get("description"),
                    is_active=bool(record.get("is_active", True)),
                    area_id=int(record["area_id"]),
                    created_at=_parse_datetime(record.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_datetime(record.get("updated_at")) or datetime.utcnow(),
                )
            )
        db.commit()

        for record in class_sessions:
            db.add(
                ClassSession(
                    id=int(record["source_id"]),
                    laboratory_id=int(record["laboratory_id"]),
                    date=_parse_date(record.get("date")) or date.today(),
                    start_time=_parse_time(record.get("start_time")) or time(7, 0),
                    end_time=_parse_time(record.get("end_time")) or time(8, 0),
                    subject_name=record.get("subject_name") or "",
                    teacher_name=record.get("teacher_name") or "",
                    needs_support=bool(record.get("needs_support", False)),
                    support_topic=record.get("support_topic"),
                    notes=record.get("notes"),
                    created_at=_parse_datetime(record.get("created_at")) or datetime.utcnow(),
                )
            )
        db.commit()

        for record in class_tutorials:
            db.add(
                ClassTutorial(
                    id=int(record["source_id"]),
                    laboratory_id=int(record["laboratory_id"]),
                    session_type=record.get("session_type") or "tutorial",
                    date=_parse_date(record.get("date")) or date.today(),
                    start_time=_parse_time(record.get("start_time")) or time(7, 0),
                    end_time=_parse_time(record.get("end_time")) or time(8, 0),
                    title=record.get("title") or "",
                    facilitator_name=record.get("facilitator_name") or "",
                    target_group=record.get("target_group"),
                    academic_unit=record.get("academic_unit"),
                    needs_support=bool(record.get("needs_support", False)),
                    support_topic=record.get("support_topic"),
                    notes=record.get("notes"),
                    created_at=_parse_datetime(record.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_datetime(record.get("updated_at")) or datetime.utcnow(),
                )
            )
        db.commit()

        for record in practice_requests:
            db.add(
                PracticeRequest(
                    id=int(record["source_id"]),
                    user_id=record.get("user_id") or "",
                    username=record.get("username") or "",
                    subject_name=record.get("subject_name"),
                    laboratory_id=int(record["laboratory_id"]),
                    date=_parse_date(record.get("date")) or date.today(),
                    start_time=_parse_time(record.get("start_time")) or time(7, 0),
                    end_time=_parse_time(record.get("end_time")) or time(8, 0),
                    needs_support=bool(record.get("needs_support", False)),
                    support_topic=record.get("support_topic"),
                    notes=record.get("notes") or "",
                    review_comment=record.get("review_comment"),
                    status=record.get("status") or "pending",
                    created_at=_parse_datetime(record.get("created_at")) or datetime.utcnow(),
                    status_updated_at=_parse_datetime(record.get("status_updated_at")) or datetime.utcnow(),
                    user_notification_read=bool(record.get("user_notification_read", True)),
                )
            )
        db.commit()

        for record in practice_materials:
            db.add(
                PracticeMaterial(
                    id=int(record["source_id"]),
                    practice_request_id=int(record["practice_request_id"]),
                    asset_id=int(record["asset_id"]),
                    material_name=record.get("material_name") or "",
                    quantity=int(record.get("quantity") or 0),
                )
            )
        db.commit()


def initialize_reservations_pocketbase_sync() -> None:
    if not reservations_pocketbase_client.enabled:
        return
    ensure_reservations_pocketbase_collections()
    try:
        if _reservations_has_remote_data() and _reservations_remote_total_records() >= _reservations_local_total_records():
            import_reservations_from_pocketbase()
        else:
            sync_reservations_to_pocketbase()
    except Exception as exc:
        logger.warning("PocketBase no pudo inicializar reservas; se continua con el cache local: %s", exc)
