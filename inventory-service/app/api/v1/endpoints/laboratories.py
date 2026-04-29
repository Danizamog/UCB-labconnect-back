from fastapi import APIRouter, Depends, HTTPException, status

from app.application.container import laboratory_repo
from app.core.dependencies import ensure_any_permission, get_current_user
from app.schemas.laboratory import LaboratoryCreate, LaboratoryResponse, LaboratoryUpdate

router = APIRouter(prefix="/laboratories", tags=["laboratories"])

_MANAGE_LABS = {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"}


@router.get("/all", response_model=list[LaboratoryResponse])
def list_laboratories_all(_: dict = Depends(get_current_user)) -> list[LaboratoryResponse]:
    return laboratory_repo.list_all()


@router.get("", response_model=list[LaboratoryResponse])
def list_laboratories(_: dict = Depends(get_current_user)) -> list[LaboratoryResponse]:
    return laboratory_repo.list_all()


@router.get("/{lab_id}", response_model=LaboratoryResponse)
def get_laboratory(lab_id: str, _: dict = Depends(get_current_user)) -> LaboratoryResponse:
    lab = laboratory_repo.get_by_id(lab_id)
    if lab is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laboratorio no encontrado")
    return lab


@router.post("", response_model=LaboratoryResponse, status_code=status.HTTP_201_CREATED)
def create_laboratory(body: LaboratoryCreate, current_user: dict = Depends(get_current_user)) -> LaboratoryResponse:
    ensure_any_permission(current_user, _MANAGE_LABS, "No tienes permisos para registrar laboratorios")
    return laboratory_repo.create(body)


@router.patch("/{lab_id}", response_model=LaboratoryResponse)
@router.put("/{lab_id}", response_model=LaboratoryResponse)
def update_laboratory(lab_id: str, body: LaboratoryUpdate, current_user: dict = Depends(get_current_user)) -> LaboratoryResponse:
    ensure_any_permission(current_user, _MANAGE_LABS, "No tienes permisos para modificar laboratorios")
    lab = laboratory_repo.update(lab_id, body)
    if lab is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laboratorio no encontrado")
    return lab


@router.delete("/{lab_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_laboratory(lab_id: str, current_user: dict = Depends(get_current_user)) -> None:
    ensure_any_permission(current_user, _MANAGE_LABS, "No tienes permisos para eliminar laboratorios")
    deleted = laboratory_repo.delete(lab_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laboratorio no encontrado")
