from fastapi import APIRouter, HTTPException, status

from app.application.container import manage_roles_use_case
from app.interfaces.http.schemas.role import RoleCreateRequest, RoleResponse, RoleUpdateRequest

router = APIRouter(prefix="/v1/roles", tags=["roles"])


@router.get("/", response_model=list[RoleResponse])
def list_roles():
    return manage_roles_use_case.list_roles()


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(role_id: int):
    try:
        return manage_roles_use_case.get_role(role_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleCreateRequest):
    try:
        return manage_roles_use_case.create_role(
            name=payload.name,
            description=payload.description,
            permissions=payload.permissions,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{role_id}", response_model=RoleResponse)
def update_role(role_id: int, payload: RoleUpdateRequest):
    try:
        return manage_roles_use_case.update_role(
            role_id=role_id,
            name=payload.name,
            description=payload.description,
            permissions=payload.permissions,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: int):
    try:
        manage_roles_use_case.delete_role(role_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
