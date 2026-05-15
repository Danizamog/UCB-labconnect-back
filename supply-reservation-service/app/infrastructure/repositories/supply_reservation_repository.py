import httpx

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.supply_reservation import SupplyReservationResponse


def _to_response(record: dict) -> SupplyReservationResponse:
    expand = record.get("expand") or {}
    stock_item_name: str | None = None
    laboratory_id = ""
    laboratory_name: str | None = None
    quantity_available = 0

    if isinstance(expand, dict):
        stock_record = expand.get("stock_item_id")
        if isinstance(stock_record, dict):
            stock_item_name = stock_record.get("name") or None
            laboratory_id = str(stock_record.get("laboratory_id") or "")
            quantity_available = int(stock_record.get("quantity_available") or 0)

            stock_expand = stock_record.get("expand") or {}
            if isinstance(stock_expand, dict):
                lab_record = stock_expand.get("laboratory_id")
                if isinstance(lab_record, dict):
                    laboratory_name = lab_record.get("name") or None

    return SupplyReservationResponse(
        id=record.get("id", ""),
        stock_item_id=record.get("stock_item_id", ""),
        stock_item_name=stock_item_name,
        laboratory_id=laboratory_id,
        laboratory_name=laboratory_name,
        quantity=int(record.get("quantity", 0)),
        quantity_available=quantity_available,
        status=record.get("status", "pending"),
        requested_by=record.get("requested_by", ""),
        requested_for=record.get("requested_for", ""),
        notes=record.get("notes", ""),
        tutorial_session_id=str(record.get("tutorial_session_id") or ""),
        lab_reservation_id=str(record.get("lab_reservation_id") or ""),
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


class SupplyReservationRepository:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{settings.pb_supply_reservations_collection}/records"
        self._expand = "stock_item_id,stock_item_id.laboratory_id"

    def list_all(
        self,
        page: int = 1,
        per_page: int = 50,
        *,
        status_filter: str | None = None,
        stock_item_id: str | None = None,
        tutorial_session_id: str | None = None,
        lab_reservation_id: str | None = None,
        requested_by: str | None = None,
    ) -> list[SupplyReservationResponse]:
        items: list[SupplyReservationResponse] = []
        current_page = page

        filters = []
        if status_filter:
            filters.append(f'status = "{status_filter}"')
        if stock_item_id:
            filters.append(f'stock_item_id = "{stock_item_id}"')
        if tutorial_session_id:
            filters.append(f'tutorial_session_id = "{tutorial_session_id}"')
        if lab_reservation_id:
            filters.append(f'lab_reservation_id = "{lab_reservation_id}"')
        if requested_by:
            filters.append(f'requested_by = "{requested_by}"')
        filter_expr = " && ".join(filters) if filters else None

        while True:
            params = {
                "page": current_page,
                "perPage": per_page,
                "sort": "-created",
                "expand": self._expand,
            }
            if filter_expr:
                params["filter"] = filter_expr

            data = self._client.request("GET", self._base, params=params)
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
                params={"expand": self._expand},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return _to_response(data)

    def sum_pending_quantity(self, stock_item_id: str, *, exclude_id: str | None = None) -> int:
        params = {
            "page": 1,
            "perPage": 200,
            "filter": f'stock_item_id = "{stock_item_id}" && status = "pending"',
        }
        try:
            data = self._client.request("GET", self._base, params=params)
        except httpx.HTTPStatusError:
            return 0
        if not isinstance(data, dict):
            return 0
        total = 0
        for record in data.get("items") or []:
            if not isinstance(record, dict):
                continue
            if exclude_id and record.get("id") == exclude_id:
                continue
            total += int(record.get("quantity") or 0)
        return total

    def create(self, payload: dict) -> SupplyReservationResponse:
        data = self._client.request("POST", self._base, payload=payload, params={"expand": self._expand})
        if not isinstance(data, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear la reserva")
        return _to_response(data)

    def update(self, reservation_id: str, payload: dict) -> SupplyReservationResponse | None:
        try:
            data = self._client.request(
                "PATCH",
                f"{self._base}/{reservation_id}",
                payload=payload,
                params={"expand": self._expand},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return _to_response(data)
