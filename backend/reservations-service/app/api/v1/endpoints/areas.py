from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user_payload
from app.models.area import Area
from app.schemas.area import AreaCreate, AreaOut, AreaUpdate

router = APIRouter(prefix="/areas", tags=["areas"])


def ensure_manager(current_user: dict):
    if current_user.get("role") not in {"admin", "lab_manager"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado para gestionar areas",
        )


@router.get("/", response_model=list[AreaOut])
def list_areas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    return (
        db.query(Area)
        .filter(Area.is_active == True)
        .order_by(Area.name.asc())
        .all()
    )


@router.get("/all", response_model=list[AreaOut])
def list_all_areas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)
    return db.query(Area).order_by(Area.name.asc()).all()


@router.post("/", response_model=AreaOut, status_code=status.HTTP_201_CREATED)
def create_area(
    payload: AreaCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    existing = db.query(Area).filter(Area.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un area con ese nombre",
        )

    area = Area(
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(area)
    db.commit()
    db.refresh(area)
    return area


@router.put("/{area_id}", response_model=AreaOut)
def update_area(
    area_id: int,
    payload: AreaUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_manager(current_user)

    area = db.query(Area).filter(Area.id == area_id).first()
    if not area:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Area no encontrada",
        )

    if payload.name is not None and payload.name != area.name:
        existing = db.query(Area).filter(Area.name == payload.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ya existe un area con ese nombre",
            )
        area.name = payload.name

    if payload.description is not None:
        area.description = payload.description

    if payload.is_active is not None:
        area.is_active = payload.is_active

    db.commit()
    db.refresh(area)
    return area
