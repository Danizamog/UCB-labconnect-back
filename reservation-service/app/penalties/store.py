from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.core.datetime_utils import parse_datetime
from app.infrastructure.pocketbase_base import PocketBaseClient
from app.schemas.penalty import PenaltyCreate, PenaltyResponse


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_iso(value: str | None) -> str:
    if value is None:
        return _utcnow_iso()
    parsed = parse_datetime(value)
    return parsed.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _build_status(record: PenaltyResponse, *, now: datetime | None = None) -> tuple[str, bool]:
    if record.lifted_at:
        return "lifted", False

    reference = now or datetime.utcnow()
    starts_at = parse_datetime(record.starts_at)
    ends_at = parse_datetime(record.ends_at)

    if reference < starts_at:
        return "scheduled", False
    if reference >= ends_at:
        return "expired", False
    return "active", True


class PenaltyStore:
    def __init__(self, client: PocketBaseClient) -> None:
        self._client = client
        self._base = f"/api/collections/{settings.pb_penalty_collection}/records"

    def _list_records(self, *, page: int = 1, per_page: int = 200, sort: str | None = None, filter_expr: str | None = None) -> list[dict]:
        items: list[dict] = []
        current_page = page

        while True:
            params: dict[str, str | int] = {"page": current_page, "perPage": per_page}
            if sort:
                params["sort"] = sort
            if filter_expr:
                params["filter"] = filter_expr

            try:
                data = self._client.request("GET", self._base, params=params)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 400 and sort:
                    fallback_params: dict[str, str | int] = {"page": current_page, "perPage": per_page}
                    if filter_expr:
                        fallback_params["filter"] = filter_expr
                    data = self._client.request("GET", self._base, params=fallback_params)
                else:
                    raise

            if not isinstance(data, dict):
                break

            records = data.get("items", [])
            if not isinstance(records, list) or not records:
                break

            for record in records:
                if isinstance(record, dict):
                    items.append(record)

            total_pages = int(data.get("totalPages", current_page))
            if current_page >= total_pages:
                break
            current_page += 1

        return items

    def _to_response(self, record: dict) -> PenaltyResponse:
        return PenaltyResponse(
            id=str(record.get("id") or "").strip(),
            user_id=str(record.get("user_id") or "").strip(),
            user_name=str(record.get("user_name") or "").strip(),
            user_email=str(record.get("user_email") or "").strip(),
            reason=str(record.get("reason") or "").strip(),
            evidence_type=str(record.get("evidence_type") or "damage_report").strip() or "damage_report",
            evidence_report_id=str(record.get("evidence_report_id") or "").strip(),
            asset_id=str(record.get("asset_id") or "").strip(),
            related_reservation_id=str(record.get("related_reservation_id") or "").strip(),
            starts_at=str(record.get("starts_at") or "").strip(),
            ends_at=str(record.get("ends_at") or "").strip(),
            notes=str(record.get("notes") or "").strip(),
            status=str(record.get("status") or "scheduled").strip() or "scheduled",
            is_active=bool(record.get("is_active", False)),
            email_sent=bool(record.get("email_sent", False)),
            created_at=str(record.get("created_at") or record.get("created") or "").strip(),
            updated_at=str(record.get("updated_at") or record.get("updated") or "").strip(),
            created_by=str(record.get("created_by") or "").strip(),
            created_by_name=str(record.get("created_by_name") or "").strip(),
            lifted_at=str(record.get("lifted_at") or "").strip(),
            lifted_by=str(record.get("lifted_by") or "").strip(),
            lifted_by_name=str(record.get("lifted_by_name") or "").strip(),
            lift_reason=str(record.get("lift_reason") or "").strip(),
        )

    def _hydrate(self, record: PenaltyResponse) -> PenaltyResponse:
        status, is_active = _build_status(record)
        return record.model_copy(update={"status": status, "is_active": is_active})

    def list_all(self) -> list[PenaltyResponse]:
        records = self._list_records(sort="-created")
        items = [self._hydrate(self._to_response(record)) for record in records]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def list_for_user(self, user_id: str) -> list[PenaltyResponse]:
        normalized_user_id = str(user_id or "").strip()
        return [item for item in self.list_all() if item.user_id == normalized_user_id]

    def get_by_id(self, penalty_id: str) -> PenaltyResponse | None:
        if not penalty_id:
            return None
        try:
            data = self._client.request("GET", f"{self._base}/{penalty_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

        if not isinstance(data, dict):
            return None
        return self._hydrate(self._to_response(data))

    def get_active_for_user(self, user_id: str) -> PenaltyResponse | None:
        normalized_user_id = str(user_id or "").strip()
        for item in self.list_for_user(normalized_user_id):
            if item.is_active:
                return item
        return None

    def create(self, body: PenaltyCreate, *, current_user: dict, email_sent: bool = False) -> PenaltyResponse:
        starts_at = _normalize_iso(body.starts_at)
        ends_at = _normalize_iso(body.ends_at)
        if parse_datetime(ends_at) <= parse_datetime(starts_at):
            raise ValueError("La fecha de fin de la penalizacion debe ser posterior al inicio")

        actor_user_id = str(current_user.get("user_id") or "").strip()
        actor_name = str(current_user.get("name") or current_user.get("username") or "Administrador").strip()
        payload = {
            "user_id": str(body.user_id or "").strip(),
            "user_name": str(body.user_name or "").strip(),
            "user_email": str(body.user_email or "").strip().lower(),
            "reason": str(body.reason or "").strip(),
            "evidence_type": body.evidence_type,
            "evidence_report_id": str(body.evidence_report_id or "").strip(),
            "asset_id": str(body.asset_id or "").strip(),
            "related_reservation_id": str(body.related_reservation_id or "").strip(),
            "starts_at": starts_at,
            "ends_at": ends_at,
            "notes": str(body.notes or "").strip(),
            "status": "scheduled",
            "is_active": False,
            "email_sent": bool(email_sent),
            "created_by": actor_user_id,
            "created_by_name": actor_name,
            "lifted_at": "",
            "lifted_by": "",
            "lifted_by_name": "",
            "lift_reason": "",
        }
        created = self._client.request("POST", self._base, payload=payload)
        if not isinstance(created, dict):
            raise ValueError("PocketBase devolvio una respuesta invalida al crear la penalizacion")
        return self._hydrate(self._to_response(created))

    def update_email_delivery(self, penalty_id: str, *, email_sent: bool) -> PenaltyResponse | None:
        existing = self.get_by_id(penalty_id)
        if existing is None:
            return None

        updated = self._client.request(
            "PATCH",
            f"{self._base}/{penalty_id}",
            payload={"email_sent": bool(email_sent)},
        )
        if not isinstance(updated, dict):
            return existing
        return self._hydrate(self._to_response(updated))

    def lift(self, penalty_id: str, *, current_user: dict, lift_reason: str = "") -> PenaltyResponse | None:
        actor_user_id = str(current_user.get("user_id") or "").strip()
        actor_name = str(current_user.get("name") or current_user.get("username") or "Administrador").strip()
        existing = self.get_by_id(penalty_id)
        if existing is None:
            return None

        updated = self._client.request(
            "PATCH",
            f"{self._base}/{penalty_id}",
            payload={
                "lifted_at": _utcnow_iso(),
                "lifted_by": actor_user_id,
                "lifted_by_name": actor_name,
                "lift_reason": str(lift_reason or "").strip(),
                "status": "lifted",
                "is_active": False,
            },
        )
        if not isinstance(updated, dict):
            return existing
        return self._hydrate(self._to_response(updated))
