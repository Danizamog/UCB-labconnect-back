from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import ensure_any_permission, get_current_user_payload, get_db
from app.infrastructure.pocketbase_sync import sync_reservations_to_pocketbase
from app.models.class_session import ClassSession
from app.models.class_tutorial import ClassTutorial
from app.models.laboratory import Laboratory
from app.models.practice_request import PracticeRequest
from app.realtime.events import publish_reservations_event
from app.schemas.class_tutorial import ClassTutorialCreate, ClassTutorialOut, ClassTutorialUpdate


router = APIRouter(prefix="/class-tutorials", tags=["class-tutorials"])
ALLOWED_SESSION_TYPES = {"class", "tutorial", "guest"}
ACTIVE_RESERVATION_STATUSES = {"pending", "approved"}


def _normalize_session_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in ALLOWED_SESSION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El tipo de sesion debe ser 'class', 'tutorial' o 'guest'",
        )
    return normalized


def _normalize_text(value: str | None, field_name: str, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise HTTPException(status_code=400, detail=f"El campo {field_name} es obligatorio")
        return None

    normalized = value.strip()
    if required and not normalized:
        raise HTTPException(status_code=400, detail=f"El campo {field_name} es obligatorio")
    return normalized or None


def _serialize_item(item: ClassTutorial) -> ClassTutorialOut:
    return ClassTutorialOut(
        id=item.id,
        laboratory_id=item.laboratory_id,
        laboratory_name=item.laboratory.name if item.laboratory else "Laboratorio desconocido",
        session_type=item.session_type,
        date=item.date,
        start_time=item.start_time,
        end_time=item.end_time,
        title=item.title,
        facilitator_name=item.facilitator_name,
        target_group=item.target_group,
        academic_unit=item.academic_unit,
        needs_support=item.needs_support,
        support_topic=item.support_topic,
        notes=item.notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _ensure_laboratory(db: Session, laboratory_id: int) -> Laboratory:
    laboratory = db.query(Laboratory).filter(Laboratory.id == laboratory_id).first()
    if not laboratory:
        raise HTTPException(status_code=404, detail="Laboratorio no encontrado")
    return laboratory


def _has_time_overlap(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and end_a > start_b


def _validate_conflicts(
    db: Session,
    *,
    laboratory_id: int,
    date_value,
    start_time,
    end_time,
    current_id: int | None = None,
) -> None:
    tutorial_query = db.query(ClassTutorial).filter(
        ClassTutorial.laboratory_id == laboratory_id,
        ClassTutorial.date == date_value,
    )
    if current_id is not None:
        tutorial_query = tutorial_query.filter(ClassTutorial.id != current_id)

    for item in tutorial_query.all():
        if _has_time_overlap(start_time, end_time, item.start_time, item.end_time):
            raise HTTPException(
                status_code=409,
                detail="Ya existe una clase o tutoria registrada en ese horario",
            )

    class_query = db.query(ClassSession).filter(
        ClassSession.laboratory_id == laboratory_id,
        ClassSession.date == date_value,
    )
    for item in class_query.all():
        if _has_time_overlap(start_time, end_time, item.start_time, item.end_time):
            raise HTTPException(
                status_code=409,
                detail="El horario ya esta ocupado por una clase programada",
            )

    practice_query = db.query(PracticeRequest).filter(
        PracticeRequest.laboratory_id == laboratory_id,
        PracticeRequest.date == date_value,
        PracticeRequest.status.in_(ACTIVE_RESERVATION_STATUSES),
    )
    for item in practice_query.all():
        if _has_time_overlap(start_time, end_time, item.start_time, item.end_time):
            raise HTTPException(
                status_code=409,
                detail="El horario ya esta comprometido por una reserva de practica",
            )


@router.get("/", response_model=list[ClassTutorialOut])
def list_class_tutorials(
    laboratory_id: int | None = Query(default=None),
    date_value: str | None = Query(default=None, alias="date"),
    session_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(ClassTutorial).options(joinedload(ClassTutorial.laboratory))

    if laboratory_id is not None:
        query = query.filter(ClassTutorial.laboratory_id == laboratory_id)
    if session_type is not None:
        query = query.filter(ClassTutorial.session_type == _normalize_session_type(session_type))
    if date_value is not None:
        try:
            parsed_date = datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Formato de fecha invalido") from exc
        query = query.filter(ClassTutorial.date == parsed_date)

    items = query.order_by(ClassTutorial.date.asc(), ClassTutorial.start_time.asc()).all()
    return [_serialize_item(item) for item in items]


@router.post("/", response_model=ClassTutorialOut, status_code=status.HTTP_201_CREATED)
def create_class_tutorial(
    payload: ClassTutorialCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(current_user, {"gestionar_tutorias"}, "No autorizado para crear clases y tutorias")

    session_type = _normalize_session_type(payload.session_type)
    title = _normalize_text(payload.title, "title", required=True)
    facilitator_name = _normalize_text(payload.facilitator_name, "facilitator_name", required=True)
    target_group = _normalize_text(payload.target_group, "target_group")
    academic_unit = _normalize_text(payload.academic_unit, "academic_unit")
    support_topic = _normalize_text(payload.support_topic, "support_topic")
    notes = _normalize_text(payload.notes, "notes")

    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser menor que la de fin.")
    if payload.needs_support and not support_topic:
        raise HTTPException(status_code=400, detail="Debe especificar el apoyo necesario.")

    _ensure_laboratory(db, payload.laboratory_id)
    _validate_conflicts(
        db,
        laboratory_id=payload.laboratory_id,
        date_value=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )

    item = ClassTutorial(
        laboratory_id=payload.laboratory_id,
        session_type=session_type,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        title=title,
        facilitator_name=facilitator_name,
        target_group=target_group,
        academic_unit=academic_unit,
        needs_support=payload.needs_support,
        support_topic=support_topic,
        notes=notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    saved = (
        db.query(ClassTutorial)
        .options(joinedload(ClassTutorial.laboratory))
        .filter(ClassTutorial.id == item.id)
        .first()
    )
    sync_reservations_to_pocketbase()
    publish_reservations_event(
        "class_tutorial.created",
        "class_tutorial",
        {
            "class_tutorial_id": saved.id,
            "laboratory_id": saved.laboratory_id,
            "date": saved.date.isoformat(),
            "session_type": saved.session_type,
        },
    )
    return _serialize_item(saved)


@router.put("/{item_id}", response_model=ClassTutorialOut)
def update_class_tutorial(
    item_id: int,
    payload: ClassTutorialUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(current_user, {"gestionar_tutorias"}, "No autorizado para editar clases y tutorias")

    item = db.query(ClassTutorial).filter(ClassTutorial.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Clase o tutoria no encontrada")

    next_laboratory_id = payload.laboratory_id if payload.laboratory_id is not None else item.laboratory_id
    next_date = payload.date if payload.date is not None else item.date
    next_start_time = payload.start_time if payload.start_time is not None else item.start_time
    next_end_time = payload.end_time if payload.end_time is not None else item.end_time

    if payload.laboratory_id is not None:
        _ensure_laboratory(db, payload.laboratory_id)
        item.laboratory_id = payload.laboratory_id
    if payload.session_type is not None:
        item.session_type = _normalize_session_type(payload.session_type)
    if payload.date is not None:
        item.date = payload.date
    if payload.start_time is not None:
        item.start_time = payload.start_time
    if payload.end_time is not None:
        item.end_time = payload.end_time
    if payload.title is not None:
        item.title = _normalize_text(payload.title, "title", required=True)
    if payload.facilitator_name is not None:
        item.facilitator_name = _normalize_text(payload.facilitator_name, "facilitator_name", required=True)
    if payload.target_group is not None:
        item.target_group = _normalize_text(payload.target_group, "target_group")
    if payload.academic_unit is not None:
        item.academic_unit = _normalize_text(payload.academic_unit, "academic_unit")
    if payload.needs_support is not None:
        item.needs_support = payload.needs_support
    if payload.support_topic is not None:
        item.support_topic = _normalize_text(payload.support_topic, "support_topic")
    if payload.notes is not None:
        item.notes = _normalize_text(payload.notes, "notes")

    if next_start_time >= next_end_time:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser menor que la de fin.")
    if item.needs_support and not item.support_topic:
        raise HTTPException(status_code=400, detail="Debe especificar el apoyo necesario.")

    _validate_conflicts(
        db,
        laboratory_id=next_laboratory_id,
        date_value=next_date,
        start_time=next_start_time,
        end_time=next_end_time,
        current_id=item.id,
    )

    db.commit()
    db.refresh(item)

    saved = (
        db.query(ClassTutorial)
        .options(joinedload(ClassTutorial.laboratory))
        .filter(ClassTutorial.id == item.id)
        .first()
    )
    sync_reservations_to_pocketbase()
    publish_reservations_event(
        "class_tutorial.updated",
        "class_tutorial",
        {
            "class_tutorial_id": saved.id,
            "laboratory_id": saved.laboratory_id,
            "date": saved.date.isoformat(),
            "session_type": saved.session_type,
        },
    )
    return _serialize_item(saved)


@router.delete("/{item_id}")
def delete_class_tutorial(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(current_user, {"gestionar_tutorias"}, "No autorizado para eliminar clases y tutorias")

    item = db.query(ClassTutorial).filter(ClassTutorial.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Clase o tutoria no encontrada")

    laboratory_id = item.laboratory_id
    date_value = item.date
    session_type = item.session_type
    db.delete(item)
    db.commit()
    sync_reservations_to_pocketbase()
    publish_reservations_event(
        "class_tutorial.deleted",
        "class_tutorial",
        {
            "class_tutorial_id": item_id,
            "laboratory_id": laboratory_id,
            "date": date_value.isoformat(),
            "session_type": session_type,
        },
    )
    return {"message": f"Registro {item_id} eliminado"}
