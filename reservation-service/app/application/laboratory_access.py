from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.application.container import laboratory_access_repo

_MANAGEMENT_PERMISSIONS = {"gestionar_reservas", "gestionar_reglas_reserva", "gestionar_accesos_laboratorio"}


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _normalize_bool(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "none", "null"}
    return bool(value)


def can_manage_laboratory_reservations(current_user: dict) -> bool:
    permissions = set(current_user.get("permissions") or [])
    role = str(current_user.get("role") or "").strip().lower()
    return (
        role in {"admin", "administrador"}
        or "*" in permissions
        or bool(permissions.intersection(_MANAGEMENT_PERMISSIONS))
    )


def ensure_user_can_reserve_laboratory(laboratory_id: str, current_user: dict) -> dict:
    lab_id = str(laboratory_id or "").strip()
    if not lab_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debes seleccionar un laboratorio para registrar la reserva",
        )

    laboratory = laboratory_access_repo.get_by_id(lab_id)
    if laboratory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Laboratorio no encontrado")

    if not _normalize_bool(laboratory.get("is_active"), default=True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El laboratorio seleccionado no esta activo para reservas",
        )

    if can_manage_laboratory_reservations(current_user):
        return laboratory

    user_role_key = str(current_user.get("role") or "").strip().lower()
    user_id = str(current_user.get("user_id") or "").strip()
    permissions = {str(permission).strip() for permission in current_user.get("permissions") or [] if str(permission).strip()}

    allowed_roles = _normalize_string_list(laboratory.get("allowed_roles"))
    if allowed_roles and user_role_key not in {role.lower() for role in allowed_roles}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para reservar este laboratorio por tu rol actual",
        )

    allowed_user_ids = _normalize_string_list(laboratory.get("allowed_user_ids"))
    if allowed_user_ids and user_id not in set(allowed_user_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No estas en la lista de usuarios autorizados para reservar este laboratorio",
        )

    required_permissions = _normalize_string_list(laboratory.get("required_permissions"))
    if required_permissions and not permissions.intersection(required_permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes el permiso requerido para reservar este laboratorio",
        )

    return laboratory
