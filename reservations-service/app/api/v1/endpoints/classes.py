from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import ensure_manager, get_current_user_payload, get_db
from app.infrastructure.pocketbase_sync import sync_reservations_to_pocketbase
from app.models.class_session import ClassSession
from app.models.laboratory import Laboratory
from app.schemas.class_session import ClassSessionCreate, ClassSessionOut, ClassSessionUpdate


router = APIRouter(prefix="/classes", tags=["classes"])


def serialize_class_session(item: ClassSession) -> ClassSessionOut:
    return ClassSessionOut(
        id=item.id,
        laboratory_id=item.laboratory_id,
        laboratory_name=item.laboratory.name if item.laboratory else "Laboratorio desconocido",
        date=item.date,
        start_time=item.start_time,
        end_time=item.end_time,
        subject_name=item.subject_name,
        teacher_name=item.teacher_name,
        needs_support=item.needs_support,
        support_topic=item.support_topic,
        notes=item.notes,
        created_at=item.created_at,
    )


@router.get("/", response_model=list[ClassSessionOut])
def list_classes(
    laboratory_id: int | None = Query(default=None),
    date_value: str | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    query = db.query(ClassSession).options(joinedload(ClassSession.laboratory))

    if laboratory_id is not None:
        query = query.filter(ClassSession.laboratory_id == laboratory_id)
    if date_value is not None:
        try:
            parsed_date = datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Formato de fecha invalido") from exc
        query = query.filter(ClassSession.date == parsed_date)

    items = query.order_by(ClassSession.date.asc(), ClassSession.start_time.asc()).all()
    return [serialize_class_session(item) for item in items]


@router.post("/", response_model=ClassSessionOut, status_code=status.HTTP_201_CREATED)
def create_class(
    payload: ClassSessionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser menor que la de fin.")
    if payload.needs_support and not payload.support_topic:
        raise HTTPException(status_code=400, detail="Debe especificar el apoyo necesario.")

    laboratory = db.query(Laboratory).filter(Laboratory.id == payload.laboratory_id).first()
    if not laboratory:
        raise HTTPException(status_code=404, detail="Laboratorio no encontrado")

    item = ClassSession(
        laboratory_id=payload.laboratory_id,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        subject_name=payload.subject_name.strip(),
        teacher_name=payload.teacher_name.strip(),
        needs_support=payload.needs_support,
        support_topic=payload.support_topic,
        notes=payload.notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    item = (
        db.query(ClassSession)
        .options(joinedload(ClassSession.laboratory))
        .filter(ClassSession.id == item.id)
        .first()
    )
    sync_reservations_to_pocketbase()
    return serialize_class_session(item)


@router.put("/{class_id}", response_model=ClassSessionOut)
def update_class(
    class_id: int,
    payload: ClassSessionUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    item = db.query(ClassSession).filter(ClassSession.id == class_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    if payload.laboratory_id is not None:
        laboratory = db.query(Laboratory).filter(Laboratory.id == payload.laboratory_id).first()
        if not laboratory:
            raise HTTPException(status_code=404, detail="Laboratorio no encontrado")
        item.laboratory_id = payload.laboratory_id
    if payload.date is not None:
        item.date = payload.date
    if payload.start_time is not None:
        item.start_time = payload.start_time
    if payload.end_time is not None:
        item.end_time = payload.end_time
    if payload.subject_name is not None:
        item.subject_name = payload.subject_name.strip()
    if payload.teacher_name is not None:
        item.teacher_name = payload.teacher_name.strip()
    if payload.needs_support is not None:
        item.needs_support = payload.needs_support
    if payload.support_topic is not None:
        item.support_topic = payload.support_topic
    if payload.notes is not None:
        item.notes = payload.notes

    if item.start_time >= item.end_time:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser menor que la de fin.")
    if item.needs_support and not item.support_topic:
        raise HTTPException(status_code=400, detail="Debe especificar el apoyo necesario.")

    db.commit()
    db.refresh(item)
    item = (
        db.query(ClassSession)
        .options(joinedload(ClassSession.laboratory))
        .filter(ClassSession.id == item.id)
        .first()
    )
    sync_reservations_to_pocketbase()
    return serialize_class_session(item)


@router.delete("/{class_id}")
def delete_class(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    item = db.query(ClassSession).filter(ClassSession.id == class_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    db.delete(item)
    db.commit()
    sync_reservations_to_pocketbase()
    return {"message": f"Clase {class_id} eliminada"}
