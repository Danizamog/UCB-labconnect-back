"""Resolucion del alcance por laboratorio para el directorio de inventario.

Centraliza la decision de "que laboratorios puede ver/operar un usuario" para
que assets, stock_items, prestamos y mantenimiento compartan la misma logica.

- Admin (role en {admin, administrador}) o usuario con permiso `*` ve todos los
  laboratorios (`resolve_accessible_lab_ids` devuelve `None`).
- En caso contrario, devuelve la lista de IDs de laboratorios donde el usuario
  esta asignado como `manager`. Si no maneja ninguno, devuelve [].

Convencion para los filtros: los recursos cuyo `laboratory_id` esta vacio se
consideran visibles para todos los usuarios autorizados (no estan asignados a
un laboratorio concreto).
"""
from __future__ import annotations


def is_global_inventory_viewer(current_user: dict) -> bool:
    role = str(current_user.get("role") or "").strip().lower()
    if role in {"admin", "administrador"}:
        return True
    permissions = current_user.get("permissions")
    return isinstance(permissions, list) and "*" in permissions


def resolve_accessible_lab_ids(current_user: dict) -> list[str] | None:
    if is_global_inventory_viewer(current_user):
        return None

    user_id = str(current_user.get("user_id") or "").strip()
    if not user_id:
        return []

    # Importamos aqui para evitar dependencias circulares con el container.
    from app.application.container import laboratory_repo

    accessible: list[str] = []
    for lab in laboratory_repo.list_all():
        if str(lab.manager or "").strip() == user_id:
            accessible.append(str(lab.id))
    return accessible


def is_lab_in_scope(laboratory_id: str | None, accessible_lab_ids: list[str] | None) -> bool:
    """Aplica la convencion: lab_id vacio es visible para todos; si hay lista,
    debe coincidir; si la lista es None (admin) siempre True."""
    if accessible_lab_ids is None:
        return True
    normalized = str(laboratory_id or "").strip()
    if not normalized:
        return True
    return normalized in accessible_lab_ids
