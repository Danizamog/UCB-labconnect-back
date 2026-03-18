from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user_payload
from app.models.laboratory import Laboratory
from app.schemas.laboratory import LaboratoryCreate, LaboratoryOut, LaboratoryUpdate

router = APIRouter(prefix="/labs", tags=["labs"])


@router.get("/", response_model=list[LaboratoryOut])
def get_labs(db: Session = Depends(get_db)):
    return (
        db.query(Laboratory)
        .filter(Laboratory.is_active == True)
        .order_by(Laboratory.id.asc())
        .all()
    )


@router.get("/all", response_model=list[LaboratoryOut])
def get_all_labs(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede ver todos los laboratorios")

    return db.query(Laboratory).order_by(Laboratory.id.asc()).all()


@router.post("/", response_model=LaboratoryOut)
def create_lab(
    payload: LaboratoryCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede crear laboratorios")

    lab = Laboratory(
        name=payload.name,
        location=payload.location,
        capacity=payload.capacity,
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(lab)
    db.commit()
    db.refresh(lab)
    return lab


@router.put("/{lab_id}", response_model=LaboratoryOut)
def update_lab(
    lab_id: int,
    payload: LaboratoryUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede editar laboratorios")

    lab = db.query(Laboratory).filter(Laboratory.id == lab_id).first()
    if not lab:
        raise HTTPException(status_code=404, detail="Laboratorio no encontrado")

    lab.name = payload.name
    lab.location = payload.location
    lab.capacity = payload.capacity
    lab.description = payload.description
    lab.is_active = payload.is_active

    db.commit()
    db.refresh(lab)
    return lab