from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import get_db, get_current_user_payload
from app.models.area import Area
from app.models.laboratory import Laboratory
from app.schemas.laboratory import LaboratoryCreate, LaboratoryOut, LaboratoryUpdate

router = APIRouter(prefix="/labs", tags=["labs"])


def ensure_manager(current_user: dict):
    if current_user.get("role") not in {"admin", "lab_manager"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado para gestionar laboratorios",
        )


def to_laboratory_out(lab: Laboratory) -> LaboratoryOut:
    return LaboratoryOut(
        id=lab.id,
        name=lab.name,
        location=lab.location,
        capacity=lab.capacity,
        description=lab.description,
        is_active=lab.is_active,
        area_id=lab.area_id,
        area_name=lab.area.name if lab.area else None,
    )


@router.get("/", response_model=list[LaboratoryOut])
def list_active_labs(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    labs = (
        db.query(Laboratory)
        .options(joinedload(Laboratory.area))
        .filter(Laboratory.is_active == True)
        .order_by(Laboratory.name.asc())
        .all()
    )
    return [to_laboratory_out(lab) for lab in labs]


@router.get("/all", response_model=list[LaboratoryOut])
def list_all_labs(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    labs = (
        db.query(Laboratory)
        .options(joinedload(Laboratory.area))
        .order_by(Laboratory.name.asc())
        .all()
    )
    return [to_laboratory_out(lab) for lab in labs]


@router.get("/{lab_id}", response_model=LaboratoryOut)
def get_lab(
    lab_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    lab = (
        db.query(Laboratory)
        .options(joinedload(Laboratory.area))
        .filter(Laboratory.id == lab_id)
        .first()
    )
    if not lab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Laboratorio no encontrado",
        )
    if current_user.get("role") not in {"admin", "lab_manager"} and not lab.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Laboratorio no disponible",
        )
    return to_laboratory_out(lab)


@router.post("/", response_model=LaboratoryOut, status_code=status.HTTP_201_CREATED)
def create_lab(
    payload: LaboratoryCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    area = db.query(Area).filter(Area.id == payload.area_id).first()
    if not area:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El area seleccionada no existe",
        )

    lab = Laboratory(
        name=payload.name,
        location=payload.location,
        capacity=payload.capacity,
        description=payload.description,
        is_active=payload.is_active,
        area_id=payload.area_id,
    )
    db.add(lab)
    db.commit()
    db.refresh(lab)

    lab = (
        db.query(Laboratory)
        .options(joinedload(Laboratory.area))
        .filter(Laboratory.id == lab.id)
        .first()
    )
    return to_laboratory_out(lab)


@router.put("/{lab_id}", response_model=LaboratoryOut)
def update_lab(
    lab_id: int,
    payload: LaboratoryUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    lab = db.query(Laboratory).filter(Laboratory.id == lab_id).first()
    if not lab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Laboratorio no encontrado",
        )

    if payload.area_id is not None:
        area = db.query(Area).filter(Area.id == payload.area_id).first()
        if not area:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El area seleccionada no existe",
            )
        lab.area_id = payload.area_id

    if payload.name is not None:
        lab.name = payload.name
    if payload.location is not None:
        lab.location = payload.location
    if payload.capacity is not None:
        lab.capacity = payload.capacity
    if payload.description is not None:
        lab.description = payload.description
    if payload.is_active is not None:
        lab.is_active = payload.is_active

    db.commit()
    db.refresh(lab)

    lab = (
        db.query(Laboratory)
        .options(joinedload(Laboratory.area))
        .filter(Laboratory.id == lab.id)
        .first()
    )
    return to_laboratory_out(lab)
