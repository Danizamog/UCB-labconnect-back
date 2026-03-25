from fastapi import APIRouter, HTTPException, status

from app.application.container import manage_roles_use_case
from app.interfaces.http.schemas.role import (
    AssignUserRoleRequest,
    RoleCreateRequest,
    RoleResponse,
    RoleUpdateRequest,
    UserWithRoleResponse,
)

router = APIRouter(prefix="/v1/roles", tags=["roles"])


@router.get("/", response_model=list[RoleResponse])
def list_roles():
    return manage_roles_use_case.list_roles()


@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleCreateRequest):
    try:
        return manage_roles_use_case.create_role(
            nombre=payload.nombre,
            descripcion=payload.descripcion,
            permisos=payload.permisos,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/users", response_model=list[UserWithRoleResponse])
def list_users_with_roles():
    return manage_roles_use_case.list_users_with_roles()


@router.patch("/users/{user_id}", response_model=UserWithRoleResponse)
def assign_role_to_user(user_id: str, payload: AssignUserRoleRequest):
    try:
        return manage_roles_use_case.assign_user_role(user_id=user_id, role_id=payload.roleId)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/users/{user_id}/role", response_model=UserWithRoleResponse)
def assign_role_to_user_shortcut(user_id: str, payload: AssignUserRoleRequest):
    try:
        return manage_roles_use_case.assign_user_role(user_id=user_id, role_id=payload.roleId)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(role_id: str):
    try:
        return manage_roles_use_case.get_role(role_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{role_id}", response_model=RoleResponse)
def update_role(role_id: str, payload: RoleUpdateRequest):
    try:
        return manage_roles_use_case.update_role(
            role_id=role_id,
            nombre=payload.nombre,
            descripcion=payload.descripcion,
            permisos=payload.permisos,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: str):
    try:
        manage_roles_use_case.delete_role(role_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
