from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from jose import jwt

from app.core.config import settings


class InventoryServiceError(RuntimeError):
    pass


inventory_service_client = httpx.Client(
    timeout=httpx.Timeout(10.0, connect=5.0),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)


def _build_service_headers() -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": "reservations-service",
            "role": "admin",
            "permissions": ["*"],
            "user_id": "reservations-service",
            "exp": int((datetime.utcnow() + timedelta(minutes=10)).timestamp()),
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def list_material_catalog() -> list[dict]:
    url = f"{settings.inventory_service_url}/v1/inventory/stock-items/"
    try:
        response = inventory_service_client.get(url)
    except httpx.HTTPError as exc:
        raise InventoryServiceError("No se pudo consultar el catalogo de materiales") from exc

    if response.status_code != 200:
        raise InventoryServiceError("No se pudo consultar el catalogo de materiales")

    payload = response.json()
    if not isinstance(payload, list):
        raise InventoryServiceError("Respuesta invalida del catalogo de materiales")
    return payload


def create_material_loan_from_practice(payload: dict) -> dict:
    url = f"{settings.inventory_service_url}/v1/inventory/loans/"
    try:
        response = inventory_service_client.post(url, json=payload, headers=_build_service_headers())
    except httpx.HTTPError as exc:
        raise InventoryServiceError("No se pudo registrar el seguimiento de materiales en inventario") from exc

    if response.status_code not in {200, 201}:
        detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
        raise InventoryServiceError(detail or "No se pudo registrar el seguimiento de materiales en inventario")

    payload = response.json()
    if not isinstance(payload, dict):
        raise InventoryServiceError("Respuesta invalida al crear seguimiento de materiales")
    return payload


def list_practice_material_loans(practice_request_id: int | None = None) -> list[dict]:
    url = f"{settings.inventory_service_url}/v1/inventory/loans/"
    params = {"source_type": "practice_request"}
    if practice_request_id is not None:
        params["practice_request_id"] = str(practice_request_id)

    try:
        response = inventory_service_client.get(url, params=params, headers=_build_service_headers())
    except httpx.HTTPError as exc:
        raise InventoryServiceError("No se pudo consultar el seguimiento de materiales") from exc

    if response.status_code != 200:
        detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
        raise InventoryServiceError(detail or "No se pudo consultar el seguimiento de materiales")

    payload = response.json()
    if not isinstance(payload, list):
        raise InventoryServiceError("Respuesta invalida del seguimiento de materiales")
    return payload


def close_material_loan(loan_id: int, return_condition: str, return_notes: str) -> dict:
    url = f"{settings.inventory_service_url}/v1/inventory/loans/{loan_id}/return"
    try:
        response = inventory_service_client.patch(
            url,
            json={
                "return_condition": return_condition,
                "return_notes": return_notes,
                "incident_notes": None,
            },
            headers=_build_service_headers(),
        )
    except httpx.HTTPError as exc:
        raise InventoryServiceError("No se pudo cerrar el seguimiento de materiales") from exc

    if response.status_code != 200:
        detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
        raise InventoryServiceError(detail or "No se pudo cerrar el seguimiento de materiales")

    payload = response.json()
    if not isinstance(payload, dict):
        raise InventoryServiceError("Respuesta invalida al cerrar seguimiento de materiales")
    return payload


def reserve_material_from_practice(payload: dict) -> dict:
    stock_item_id = payload.get("stock_item_id")
    if stock_item_id is None:
        raise InventoryServiceError("No se pudo reservar el material solicitado")

    url = f"{settings.inventory_service_url}/v1/inventory/stock-items/{stock_item_id}/movements"
    request_payload = {
        "movement_type": "reservation_hold",
        "quantity": payload.get("quantity"),
        "reference_type": "practice_request",
        "reference_id": payload.get("practice_request_id"),
        "notes": payload.get("notes"),
    }

    try:
        response = inventory_service_client.post(url, json=request_payload, headers=_build_service_headers())
    except httpx.HTTPError as exc:
        raise InventoryServiceError("No se pudo reservar el stock de materiales") from exc

    if response.status_code not in {200, 201}:
        detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
        raise InventoryServiceError(detail or "No se pudo reservar el stock de materiales")

    payload = response.json()
    if not isinstance(payload, dict):
        raise InventoryServiceError("Respuesta invalida al reservar stock de materiales")
    return payload


def release_material_from_practice(payload: dict) -> dict:
    stock_item_id = payload.get("stock_item_id")
    if stock_item_id is None:
        raise InventoryServiceError("No se pudo liberar el stock de materiales")

    url = f"{settings.inventory_service_url}/v1/inventory/stock-items/{stock_item_id}/movements"
    request_payload = {
        "movement_type": "reservation_release",
        "quantity": payload.get("quantity"),
        "reference_type": "practice_request",
        "reference_id": payload.get("practice_request_id"),
        "notes": payload.get("notes"),
    }

    try:
        response = inventory_service_client.post(url, json=request_payload, headers=_build_service_headers())
    except httpx.HTTPError as exc:
        raise InventoryServiceError("No se pudo liberar el stock reservado") from exc

    if response.status_code not in {200, 201}:
        detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
        raise InventoryServiceError(detail or "No se pudo liberar el stock reservado")

    payload = response.json()
    if not isinstance(payload, dict):
        raise InventoryServiceError("Respuesta invalida al liberar stock reservado")
    return payload
