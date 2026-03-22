from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user_payload
from app.models.laboratory import Laboratory
from app.models.practice_material import PracticeMaterial
from app.models.practice_request import PracticeRequest
from app.schemas.practice_request import PracticeRequestCreate
from app.schemas.reservation_status import PracticeStatusUpdate

router = APIRouter(prefix="/practice-planning", tags=["practice-planning"])


MATERIALS_CATALOG = {
    1: "Multimetro",
    2: "Cable UTP",
    3: "Protoboard",
    4: "Microscopio",
}


def ensure_manager(current_user: dict):
    if current_user.get("role") not in {"admin", "lab_manager"}:
        raise HTTPException(status_code=403, detail="Solo personal autorizado puede revisar reservas")


def serialize_practice(practice: PracticeRequest):
    return {
        "id": practice.id,
        "user_id": practice.user_id,
        "username": practice.username,
        "laboratory_id": practice.laboratory_id,
        "laboratory_name": practice.laboratory.name if practice.laboratory else "Laboratorio desconocido",
        "date": practice.date,
        "start_time": practice.start_time,
        "end_time": practice.end_time,
        "needs_support": practice.needs_support,
        "support_topic": practice.support_topic,
        "notes": practice.notes,
        "review_comment": practice.review_comment,
        "status": practice.status,
        "created_at": practice.created_at,
        "status_updated_at": practice.status_updated_at,
        "user_notification_read": practice.user_notification_read,
        "materials": [
            {
                "id": material.id,
                "asset_id": material.asset_id,
                "material_name": material.material_name,
                "quantity": material.quantity,
            }
            for material in practice.materials
        ],
    }


@router.post("/")
def create_practice_planning(
    payload: PracticeRequestCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    today = date.today()
    max_allowed_date = today + timedelta(days=30)

    if payload.date < today:
        raise HTTPException(status_code=400, detail="No puedes reservar en una fecha pasada")
    if payload.date > max_allowed_date:
        raise HTTPException(status_code=400, detail="Solo puedes reservar dentro de los proximos 30 dias")
    if payload.start_time < time(9, 0) or payload.start_time > time(19, 0):
        raise HTTPException(status_code=400, detail="La hora de inicio debe estar entre 09:00 y 19:00")
    if payload.end_time < time(9, 0) or payload.end_time > time(19, 0):
        raise HTTPException(status_code=400, detail="La hora de fin debe estar entre 09:00 y 19:00")
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser menor que la hora de fin")
    if not payload.notes or not payload.notes.strip():
        raise HTTPException(status_code=400, detail="Las observaciones son obligatorias")
    if payload.needs_support and (not payload.support_topic or not payload.support_topic.strip()):
        raise HTTPException(status_code=400, detail="Debes indicar el tipo de apoyo requerido")

    laboratory = db.query(Laboratory).filter(Laboratory.id == payload.laboratory_id).first()
    if not laboratory:
        raise HTTPException(status_code=404, detail="Laboratorio no encontrado")
    if not laboratory.is_active:
        raise HTTPException(status_code=400, detail="El laboratorio seleccionado no esta activo")

    overlapping = db.query(PracticeRequest).filter(
        PracticeRequest.laboratory_id == payload.laboratory_id,
        PracticeRequest.date == payload.date,
        PracticeRequest.start_time < payload.end_time,
        PracticeRequest.end_time > payload.start_time,
        PracticeRequest.status.in_(["pending", "approved"]),
    ).first()

    if overlapping:
        raise HTTPException(status_code=409, detail="El laboratorio ya esta reservado en ese horario")

    practice = PracticeRequest(
        user_id=current_user["user_id"],
        username=current_user["username"],
        laboratory_id=payload.laboratory_id,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        needs_support=payload.needs_support,
        support_topic=payload.support_topic,
        notes=payload.notes,
        review_comment=None,
        status="pending",
        status_updated_at=datetime.utcnow(),
        user_notification_read=True,
    )

    db.add(practice)
    db.flush()

    for material in payload.materials:
        if material.quantity <= 0:
            raise HTTPException(status_code=400, detail="La cantidad solicitada de materiales debe ser mayor a 0")
        material_name = material.material_name or MATERIALS_CATALOG.get(material.asset_id, f"Material {material.asset_id}")
        db.add(
            PracticeMaterial(
                practice_request_id=practice.id,
                asset_id=material.asset_id,
                material_name=material_name,
                quantity=material.quantity,
            )
        )

    db.commit()
    db.refresh(practice)
    return serialize_practice(practice)


@router.get("/my")
def get_my_practice_plannings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    practices = (
        db.query(PracticeRequest)
        .filter(PracticeRequest.user_id == current_user["user_id"])
        .order_by(PracticeRequest.created_at.desc())
        .all()
    )
    return [serialize_practice(practice) for practice in practices]


@router.get("/my/notifications")
def get_my_notifications(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    practices = (
        db.query(PracticeRequest)
        .filter(
            PracticeRequest.user_id == current_user["user_id"],
            PracticeRequest.status != "pending",
        )
        .order_by(PracticeRequest.status_updated_at.desc())
        .all()
    )
    return [
        {
            "id": practice.id,
            "title": f"Solicitud {practice.status}",
            "message": f"Tu reserva para {practice.laboratory.name if practice.laboratory else 'el laboratorio'} fue {practice.status}.",
            "status": practice.status,
            "review_comment": practice.review_comment,
            "created_at": practice.status_updated_at,
            "read": practice.user_notification_read,
            "laboratory_name": practice.laboratory.name if practice.laboratory else "Laboratorio",
            "date": practice.date,
            "start_time": practice.start_time,
            "end_time": practice.end_time,
        }
        for practice in practices
    ]


@router.patch("/{practice_id}/notifications/read")
def mark_notification_as_read(
    practice_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    practice = (
        db.query(PracticeRequest)
        .filter(
            PracticeRequest.id == practice_id,
            PracticeRequest.user_id == current_user["user_id"],
        )
        .first()
    )
    if not practice:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")

    practice.user_notification_read = True
    db.commit()
    return {"ok": True}


@router.get("/")
def get_all_practice_plannings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    practices = (
        db.query(PracticeRequest)
        .order_by(PracticeRequest.created_at.desc())
        .all()
    )
    return [serialize_practice(practice) for practice in practices]


@router.patch("/{practice_id}/status")
def update_practice_status(
    practice_id: int,
    payload: PracticeStatusUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    allowed_status = {"approved", "rejected", "cancelled", "pending"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado invalido")

    practice = db.query(PracticeRequest).filter(PracticeRequest.id == practice_id).first()
    if not practice:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")

    practice.status = payload.status
    practice.review_comment = payload.review_comment
    practice.status_updated_at = datetime.utcnow()
    practice.user_notification_read = False
    db.commit()
    db.refresh(practice)

    return serialize_practice(practice)
