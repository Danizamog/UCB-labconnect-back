import httpx

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.supply_reservation import SupplyReservationResponse


def _to_response(record: dict) -> SupplyReservationResponse:
    expand = record.get("expand") or {}
    stock_item_name: str | None = None
    if isinstance(expand, dict):
        stock_record = expand.get("stock_item_id")
        if isinstance(stock_record, dict):
            stock_item_name = stock_record.get("name") or None

    return SupplyReservationResponse(
        id=record.get("id", ""),
        stock_item_id=record.get("stock_item_id", ""),
        stock_item_name=stock_item_name,
        quantity=int(record.get("quantity", 0)),
        status=record.get("status", "pending"),
        requested_by=record.get("requested_by", ""),
        requested_for=record.get("requested_for", ""),
        notes=record.get("notes", ""),
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


class SupplyReservationRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{settings.pb_supply_reservations_collection}/records"

    def list_all(self, page: int = 1, per_page: int = 50) -> list[SupplyReservationResponse]:
        items: list[SupplyReservationResponse] = []
        current_page = page

        while True:
            data = self._client.request(
                "GET",
                self._base,
                params={
                    "page": current_page,
                    "perPage": per_page,
                    "sort": "-created",
                    "expand": "stock_item_id",
                },
            )
            if not isinstance(data, dict):
                break
            records = data.get("items", [])
            if not isinstance(records, list) or not records:
                break
            items.extend(_to_response(r) for r in records if isinstance(r, dict))
            total_pages = int(data.get("totalPages", current_page))
            if current_page >= total_pages:
                break
            current_page += 1

        return items

    def get_by_id(self, reservation_id: str) -> SupplyReservationResponse | None:
        try:
            data = self._client.request(
                "GET",
                f"{self._base}/{reservation_id}",
                params={"expand": "stock_item_id"},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return _to_response(data)

    def create(self, payload: dict) -> SupplyReservationResponse:
        data = self._client.request("POST", self._base, payload=payload, params={"expand": "stock_item_id"})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear la reserva")
        return _to_response(data)

    def update(self, reservation_id: str, payload: dict) -> SupplyReservationResponse | None:
        try:
            data = self._client.request(
                "PATCH",
                f"{self._base}/{reservation_id}",
                payload=payload,
                params={"expand": "stock_item_id"},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return _to_response(data)
