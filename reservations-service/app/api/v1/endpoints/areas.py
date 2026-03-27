from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import ensure_any_permission, get_current_user_payload, get_db
from app.infrastructure.pocketbase_sync import sync_reservations_to_pocketbase
from app.models.area import Area
from app.models.laboratory import Laboratory
from app.schemas.area import AreaCreate, AreaOut, AreaUpdate


router = APIRouter(prefix="/areas", tags=["areas"])


def serialize_area(area: Area) -> AreaOut:
    return AreaOut(
        id=area.id,
        name=area.name,
        description=area.description,
        is_active=area.is_active,
    )


@router.get("/", response_model=list[AreaOut])
def list_active_areas(db: Session = Depends(get_db)):
    rows = db.query(Area).filter(Area.is_active.is_(True)).order_by(Area.name.asc()).all()
    return [serialize_area(area) for area in rows]


@router.get("/all", response_model=list[AreaOut])
def list_all_areas(
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
        "No autorizado para ver todas las areas",
    )
    rows = db.query(Area).order_by(Area.name.asc()).all()
    return [serialize_area(area) for area in rows]


@router.post("/", response_model=AreaOut, status_code=status.HTTP_201_CREATED)
def create_area(
    payload: AreaCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No autorizado para crear areas",
    )

    existing = db.query(Area).filter(Area.name == payload.name.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un area con ese nombre")

    area = Area(
        name=payload.name.strip(),
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(area)
    db.commit()
    db.refresh(area)
    sync_reservations_to_pocketbase()
    return serialize_area(area)


@router.put("/{area_id}", response_model=AreaOut)
def update_area(
    area_id: int,
    payload: AreaUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No autorizado para editar areas",
    )

    area = db.query(Area).filter(Area.id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="Area no encontrada")

    if payload.name is not None:
        normalized_name = payload.name.strip()
        duplicate = db.query(Area).filter(Area.name == normalized_name, Area.id != area_id).first()
        if duplicate:
            raise HTTPException(status_code=400, detail="Ya existe un area con ese nombre")
        area.name = normalized_name

    if payload.description is not None:
        area.description = payload.description
    if payload.is_active is not None:
        area.is_active = payload.is_active

    db.commit()
    db.refresh(area)
    sync_reservations_to_pocketbase()
    return serialize_area(area)


@router.delete("/{area_id}")
def delete_area(
    area_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_payload),
):
    ensure_any_permission(
        current_user,
        {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"},
        "No autorizado para eliminar areas",
    )

    area = db.query(Area).filter(Area.id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="Area no encontrada")

    has_labs = db.query(Laboratory.id).filter(Laboratory.area_id == area_id).first() is not None
    if has_labs:
        raise HTTPException(
            status_code=400,
            detail="No se puede eliminar el area mientras tenga laboratorios asociados",
        )

    db.delete(area)
    db.commit()
    sync_reservations_to_pocketbase()
    return {"message": "Area eliminada"}
