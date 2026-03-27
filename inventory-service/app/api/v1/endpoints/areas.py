from fastapi import APIRouter, Depends, HTTPException, status

from app.application.container import area_repo
from app.core.dependencies import get_current_user
from app.schemas.area import AreaCreate, AreaResponse, AreaUpdate

router = APIRouter(prefix="/areas", tags=["areas"])


@router.get("/all", response_model=list[AreaResponse])
def list_areas_all() -> list[AreaResponse]:
    return area_repo.list_all()


@router.get("", response_model=list[AreaResponse])
def list_areas() -> list[AreaResponse]:
    return area_repo.list_all()


@router.get("/{area_id}", response_model=AreaResponse)
def get_area(area_id: str, _: dict = Depends(get_current_user)) -> AreaResponse:
    area = area_repo.get_by_id(area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area no encontrada")
    return area


@router.post("", response_model=AreaResponse, status_code=status.HTTP_201_CREATED)
def create_area(body: AreaCreate, _: dict = Depends(get_current_user)) -> AreaResponse:
    return area_repo.create(body)


@router.patch("/{area_id}", response_model=AreaResponse)
@router.put("/{area_id}", response_model=AreaResponse)
def update_area(area_id: str, body: AreaUpdate, _: dict = Depends(get_current_user)) -> AreaResponse:
    area = area_repo.update(area_id, body)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area no encontrada")
    return area


@router.delete("/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_area(area_id: str, _: dict = Depends(get_current_user)) -> None:
    deleted = area_repo.delete(area_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area no encontrada")
