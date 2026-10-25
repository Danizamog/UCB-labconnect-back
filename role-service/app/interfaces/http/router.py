from datetime import date, datetime
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.application.container import manage_roles_use_case
from app.core.dependencies import ensure_any_permission, get_current_user_payload
from app.interfaces.http.schemas.role import AssignUserRoleRequest, RoleCreateRequest, RoleResponse, RoleUpdateRequest, UserWithRoleResponse

router = APIRouter(prefix="/v1/roles", tags=["roles"])
logger = logging.getLogger(__name__)
VIEW_ROLES = {"consultar_roles", "gestionar_roles", "asignar_roles", "revisar_accesos_rbac"}
VIEW_HISTORY = {"gestionar_roles", "asignar_roles", "revisar_accesos_rbac", "consultar_auditoria_seguridad"}


def _execute(operation):
    try:
        return operation()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        logger.warning("No se pudo completar una operacion RBAC: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="No se pudo completar la operacion de roles y su auditoria. Recarga antes de reintentar.") from exc


@router.get("/", response_model=list[RoleResponse])
def list_roles(current_user: dict = Depends(get_current_user_payload)):
    ensure_any_permission(current_user, VIEW_ROLES, "No autorizado para ver roles")
    return _execute(manage_roles_use_case.list_roles)


@router.get("/permissions/catalog")
def list_permissions_catalog(current_user: dict = Depends(get_current_user_payload)):
    ensure_any_permission(current_user, VIEW_ROLES, "No autorizado para ver permisos")
    return manage_roles_use_case.list_permissions_catalog()


@router.get("/history")
def list_history(page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=100),
                 query: str = Query("", max_length=150), action: str = Query("", max_length=60),
                 date_from: date | None = None, date_to: date | None = None, snapshot_at: datetime | None = None,
                 current_user: dict = Depends(get_current_user_payload)):
    ensure_any_permission(current_user, VIEW_HISTORY, "No autorizado para consultar el historial de roles")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="La fecha inicial debe ser anterior a la final")
    if date_to == date.max:
        raise HTTPException(status_code=400, detail="La fecha final esta fuera del rango admitido")
    return _execute(lambda: manage_roles_use_case.list_history(page=page, per_page=per_page, query=query.strip(), action=action,
                                                              date_from=date_from, date_to=date_to, snapshot_at=snapshot_at))


@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleCreateRequest, current_user: dict = Depends(get_current_user_payload)):
    ensure_any_permission(current_user, {"gestionar_roles"}, "No autorizado para crear roles")
    return _execute(lambda: manage_roles_use_case.create_role(payload.nombre, payload.descripcion, payload.permisos,
                                                             actor=current_user, reason=payload.reason))


@router.get("/users", response_model=list[UserWithRoleResponse])
def list_users_with_roles(current_user: dict = Depends(get_current_user_payload)):
    ensure_any_permission(current_user, {"gestionar_roles", "asignar_roles", "revisar_accesos_rbac"}, "No autorizado para ver usuarios y roles")
    return _execute(manage_roles_use_case.list_users_with_roles)


@router.patch("/users/{user_id}", response_model=UserWithRoleResponse)
@router.patch("/users/{user_id}/role", response_model=UserWithRoleResponse)
def assign_role_to_user(user_id: str, payload: AssignUserRoleRequest, current_user: dict = Depends(get_current_user_payload)):
    ensure_any_permission(current_user, {"asignar_roles"}, "No autorizado para asignar roles")
    return _execute(lambda: manage_roles_use_case.assign_user_role(user_id, payload.roleId or None, actor=current_user, reason=payload.reason))


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(role_id: str, current_user: dict = Depends(get_current_user_payload)):
    ensure_any_permission(current_user, VIEW_ROLES, "No autorizado para ver roles")
    return _execute(lambda: manage_roles_use_case.get_role(role_id))


@router.put("/{role_id}", response_model=RoleResponse)
@router.patch("/{role_id}", response_model=RoleResponse)
def update_role(role_id: str, payload: RoleUpdateRequest, current_user: dict = Depends(get_current_user_payload)):
    ensure_any_permission(current_user, {"gestionar_roles"}, "No autorizado para editar roles")
    return _execute(lambda: manage_roles_use_case.update_role(role_id, payload.nombre, payload.descripcion, payload.permisos,
                                                             actor=current_user, reason=payload.reason))


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_role(role_id: str, reason: str = Query(min_length=5, max_length=500), current_user: dict = Depends(get_current_user_payload)):
    ensure_any_permission(current_user, {"gestionar_roles"}, "No autorizado para eliminar roles")
    _execute(lambda: manage_roles_use_case.delete_role(role_id, actor=current_user, reason=reason))
    return Response(status_code=204)
