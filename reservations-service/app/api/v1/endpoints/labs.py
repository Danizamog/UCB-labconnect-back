from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import ensure_any_permission, get_current_user_payload, get_db, get_optional_current_user_payload
from app.infrastructure.pocketbase_sync import sync_reservations_to_pocketbase
from app.models.area import Area
from app.models.laboratory import Laboratory
from app.schemas.laboratory import LaboratoryCreate, LaboratoryOut, LaboratoryUpdate


router = APIRouter(prefix="/labs", tags=["labs"])


def serialize_laboratory(lab: Laboratory) -> LaboratoryOut:
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
def list_active_labs(db: Session = Depends(get_db)):
    labs = (
        db.query(Laboratory)
        .options(joinedload(Laboratory.area))
        .filter(Laboratory.is_active.is_(True))
        .order_by(Laboratory.name.asc())
        .all()
    )
    return [serialize_laboratory(lab) for lab in labs]


@router.get("/all", response_model=list[LaboratoryOut])
def list_all_labs(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {
            "gestionar_reservas",
            "gestionar_reservas_materiales",
            "gestionar_reglas_reserva",
            "gestionar_accesos_laboratorio",
            "generar_reportes",
            "consultar_estadisticas",
            "gestionar_inventario",
            "gestionar_stock",
            "gestionar_estado_equipos",
            "gestionar_mantenimiento",
            "gestionar_prestamos",
            "adjuntar_evidencia_inventario",
            "gestionar_reactivos_quimicos",
        },
        "No autorizado para ver todos los laboratorios",
    )
    labs = (
        db.query(Laboratory)
        .options(joinedload(Laboratory.area))
        .order_by(Laboratory.name.asc())
        .all()
    )
    return [serialize_laboratory(lab) for lab in labs]


@router.get("/{lab_id}", response_model=LaboratoryOut)
def get_lab(
    lab_id: int,
    db: Session = Depends(get_db),
    current_user: dict | None = Depends(get_optional_current_user_payload),
):
    lab = (
        db.query(Laboratory)
        .options(joinedload(Laboratory.area))
        .filter(Laboratory.id == lab_id)
        .first()
    )
    if not lab:
        raise HTTPException(status_code=404, detail="Laboratorio no encontrado")

    if not lab.is_active and (not current_user or current_user.get("role") not in {"admin", "lab_manager", "encargado"}):
        raise HTTPException(status_code=404, detail="Laboratorio no disponible")

    return serialize_laboratory(lab)


@router.post("/", response_model=LaboratoryOut, status_code=status.HTTP_201_CREATED)
def create_lab(
    payload: LaboratoryCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No autorizado para crear laboratorios",
    )

    area = db.query(Area).filter(Area.id == payload.area_id).first()
    if not area:
        raise HTTPException(status_code=400, detail="El area seleccionada no existe")

    duplicate = db.query(Laboratory).filter(Laboratory.name == payload.name.strip()).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="Ya existe un laboratorio con ese nombre")

    lab = Laboratory(
        name=payload.name.strip(),
        location=payload.location.strip(),
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
    sync_reservations_to_pocketbase()
    return serialize_laboratory(lab)


@router.put("/{lab_id}", response_model=LaboratoryOut)
def update_lab(
    lab_id: int,
    payload: LaboratoryUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No autorizado para editar laboratorios",
    )

    lab = db.query(Laboratory).filter(Laboratory.id == lab_id).first()
    if not lab:
        raise HTTPException(status_code=404, detail="Laboratorio no encontrado")

    if payload.area_id is not None:
        area = db.query(Area).filter(Area.id == payload.area_id).first()
        if not area:
            raise HTTPException(status_code=400, detail="El area seleccionada no existe")
        lab.area_id = payload.area_id

    if payload.name is not None:
        normalized_name = payload.name.strip()
        duplicate = db.query(Laboratory).filter(Laboratory.name == normalized_name, Laboratory.id != lab_id).first()
        if duplicate:
            raise HTTPException(status_code=400, detail="Ya existe un laboratorio con ese nombre")
        lab.name = normalized_name
    if payload.location is not None:
        lab.location = payload.location.strip()
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
    sync_reservations_to_pocketbase()
    return serialize_laboratory(lab)


@router.delete("/{lab_id}")
def delete_lab(
    lab_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No autorizado para eliminar laboratorios",
    )

    lab = db.query(Laboratory).filter(Laboratory.id == lab_id).first()
    if not lab:
        raise HTTPException(status_code=404, detail="Laboratorio no encontrado")

    db.delete(lab)
    db.commit()
    sync_reservations_to_pocketbase()
    return {"message": "Laboratorio eliminado"}
