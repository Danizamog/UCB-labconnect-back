from fastapi import APIRouter, Depends, HTTPException, status

from app.application.container import area_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.schemas.area import AreaCreate, AreaResponse, AreaUpdate

router = APIRouter(prefix="/areas", tags=["areas"])

_MANAGE_AREAS = {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"}


@router.get("/all", response_model=list[AreaResponse])
def list_areas_all(_: dict = Depends(get_current_user)) -> list[AreaResponse]:
    return area_repo.list_all()


@router.get("", response_model=list[AreaResponse])
def list_areas(_: dict = Depends(get_current_user)) -> list[AreaResponse]:
    return area_repo.list_all()


@router.get("/{area_id}", response_model=AreaResponse)
def get_area(area_id: str, _: dict = Depends(get_current_user)) -> AreaResponse:
    area = area_repo.get_by_id(area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area no encontrada")
    return area


@router.post("", response_model=AreaResponse, status_code=status.HTTP_201_CREATED)
def create_area(body: AreaCreate, current_user: dict = Depends(get_current_user)) -> AreaResponse:
    ensure_any_permission(current_user, _MANAGE_AREAS, "No tienes permisos para registrar areas")
    return area_repo.create(body)


@router.patch("/{area_id}", response_model=AreaResponse)
@router.put("/{area_id}", response_model=AreaResponse)
def update_area(area_id: str, body: AreaUpdate, current_user: dict = Depends(get_current_user)) -> AreaResponse:
    ensure_any_permission(current_user, _MANAGE_AREAS, "No tienes permisos para modificar areas")
    area = area_repo.update(area_id, body)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area no encontrada")
    return area


@router.delete("/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_area(area_id: str, current_user: dict = Depends(get_current_user)) -> None:
    ensure_any_permission(current_user, _MANAGE_AREAS, "No tienes permisos para eliminar areas")
    deleted = area_repo.delete(area_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area no encontrada")
