from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user_payload
from app.models.laboratory import Laboratory
from app.models.practice_request import PracticeRequest
from app.models.practice_material import PracticeMaterial
from app.schemas.practice_request import PracticeRequestCreate
from app.schemas.reservation_status import PracticeStatusUpdate

router = APIRouter(prefix="/practice-planning", tags=["practice-planning"])


MATERIALS_CATALOG = {
    1: "Multímetro",
    2: "Cable UTP",
    3: "Protoboard",
    4: "Microscopio",
}


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
        "status": practice.status,
        "created_at": practice.created_at,
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
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser menor que la hora de fin")

    laboratory = db.query(Laboratory).filter(Laboratory.id == payload.laboratory_id).first()
    if not laboratory:
        raise HTTPException(status_code=404, detail="Laboratorio no encontrado")

    overlapping = db.query(PracticeRequest).filter(
        PracticeRequest.laboratory_id == payload.laboratory_id,
        PracticeRequest.date == payload.date,
        PracticeRequest.start_time < payload.end_time,
        PracticeRequest.end_time > payload.start_time,
        PracticeRequest.status.in_(["pending", "approved"]),
    ).first()

    if overlapping:
        raise HTTPException(status_code=409, detail="El laboratorio ya está reservado en ese horario")

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
        status="pending",
    )

    db.add(practice)
    db.flush()

    for material in payload.materials:
        material_name = MATERIALS_CATALOG.get(material.asset_id, f"Material {material.asset_id}")
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


@router.get("/")
def get_all_practice_plannings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede ver todas las reservas")

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
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede actualizar el estado de las reservas")

    allowed_status = {"approved", "rejected", "cancelled", "pending"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Estado inválido")

    practice = db.query(PracticeRequest).filter(PracticeRequest.id == practice_id).first()
    if not practice:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")

    practice.status = payload.status
    db.commit()
    db.refresh(practice)

    return serialize_practice(practice)