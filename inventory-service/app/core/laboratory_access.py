"""Resolucion del alcance por laboratorio para el directorio de inventario.

Centraliza la decision de "que laboratorios puede ver/operar un usuario" para
que assets, stock_items, prestamos y mantenimiento compartan la misma logica.

- Devuelve la lista de IDs de laboratorios donde el usuario
  esta asignado como `manager`. Si no maneja ninguno, devuelve [].

Los recursos sin `laboratory_id` quedan visibles solo para usuarios con alcance
global; un encargado opera exclusivamente recursos de su laboratorio asignado.
"""
from __future__ import annotations


def is_global_inventory_viewer(current_user: dict) -> bool:
    permissions = {str(value).strip() for value in current_user.get("permissions") or []}
    return "gestionar_estructura_laboratorios" in permissions


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
    """Si hay lista limitada, el recurso debe pertenecer a uno de esos labs."""
    if accessible_lab_ids is None:
        return True
    normalized = str(laboratory_id or "").strip()
    return bool(normalized) and normalized in accessible_lab_ids
