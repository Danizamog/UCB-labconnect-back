from fastapi import APIRouter, Depends, HTTPException, status, Query

from app.application.container import laboratory_repo
from app.core.dependencies import get_current_user
from app.schemas.laboratory import LaboratoryCreate, LaboratoryResponse, LaboratoryUpdate

router = APIRouter(prefix="/laboratories", tags=["laboratories"])


@router.get("/all", response_model=list[LaboratoryResponse])
def list_laboratories_all() -> list[LaboratoryResponse]:
    return laboratory_repo.list_all()


@router.get("", response_model=list[LaboratoryResponse])
def list_laboratories(
    name: str | None = Query(default=None, description="Filter by laboratory name (contains)"),
    area_id: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    sort: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=200, ge=1, le=1000),
) -> list[LaboratoryResponse]:
    return laboratory_repo.list_all(page=page, per_page=per_page, name=name, area_id=area_id, is_active=is_active, sort=sort)


@router.get("/{lab_id}", response_model=LaboratoryResponse)
def get_laboratory(lab_id: str, _: dict = Depends(get_current_user)) -> LaboratoryResponse:
    lab = laboratory_repo.get_by_id(lab_id)
    if lab is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laboratorio no encontrado")
    return lab


@router.post("", response_model=LaboratoryResponse, status_code=status.HTTP_201_CREATED)
def create_laboratory(body: LaboratoryCreate, _: dict = Depends(get_current_user)) -> LaboratoryResponse:
    return laboratory_repo.create(body)


@router.patch("/{lab_id}", response_model=LaboratoryResponse)
@router.put("/{lab_id}", response_model=LaboratoryResponse)
def update_laboratory(lab_id: str, body: LaboratoryUpdate, _: dict = Depends(get_current_user)) -> LaboratoryResponse:
    lab = laboratory_repo.update(lab_id, body)
    if lab is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laboratorio no encontrado")
    return lab


@router.delete("/{lab_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_laboratory(lab_id: str, _: dict = Depends(get_current_user)) -> None:
    deleted = laboratory_repo.delete(lab_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laboratorio no encontrado")
