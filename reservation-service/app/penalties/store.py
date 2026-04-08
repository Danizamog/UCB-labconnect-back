from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from pydantic import ValidationError

from app.core.datetime_utils import parse_datetime
from app.infrastructure.local_store import LocalJsonStore
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
    def __init__(self) -> None:
        self._items: list[PenaltyResponse] = []
        self._lock = Lock()
        self._local_store = LocalJsonStore("user_penalty")
        self._load_from_local_store()

    def _load_from_local_store(self) -> None:
        loaded: list[PenaltyResponse] = []
        for raw_record in self._local_store.list():
            try:
                loaded.append(PenaltyResponse.model_validate(raw_record))
            except ValidationError:
                continue

        with self._lock:
            self._items = loaded

    def _persist(self, record: PenaltyResponse, *, operation: str = "update") -> None:
        self._local_store.upsert(record.id, record.model_dump(), operation=operation)

    def _hydrate(self, record: PenaltyResponse) -> PenaltyResponse:
        status, is_active = _build_status(record)
        return record.model_copy(update={"status": status, "is_active": is_active})

    def list_all(self) -> list[PenaltyResponse]:
        with self._lock:
            items = [self._hydrate(item) for item in self._items]

        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def list_for_user(self, user_id: str) -> list[PenaltyResponse]:
        normalized_user_id = str(user_id or "").strip()
        return [item for item in self.list_all() if item.user_id == normalized_user_id]

    def get_by_id(self, penalty_id: str) -> PenaltyResponse | None:
        with self._lock:
            for item in self._items:
                if item.id == penalty_id:
                    return self._hydrate(item)
        return None

    def get_active_for_user(self, user_id: str) -> PenaltyResponse | None:
        normalized_user_id = str(user_id or "").strip()
        for item in self.list_for_user(normalized_user_id):
            if item.is_active:
                return item
        return None

    def get_blocking_for_user(self, user_id: str) -> PenaltyResponse | None:
        normalized_user_id = str(user_id or "").strip()
        for item in self.list_for_user(normalized_user_id):
            if item.status in {"active", "scheduled"}:
                return item
        return None

    def create(self, body: PenaltyCreate, *, current_user: dict, email_sent: bool = False) -> PenaltyResponse:
        starts_at = _normalize_iso(body.starts_at)
        ends_at = _normalize_iso(body.ends_at)
        if parse_datetime(ends_at) <= parse_datetime(starts_at):
            raise ValueError("La fecha de fin de la penalizacion debe ser posterior al inicio")

        actor_user_id = str(current_user.get("user_id") or "").strip()
        actor_name = str(current_user.get("name") or current_user.get("username") or "Administrador").strip()
        now_iso = _utcnow_iso()

        record = PenaltyResponse(
            id=str(uuid4()),
            user_id=str(body.user_id or "").strip(),
            user_name=str(body.user_name or "").strip(),
            user_email=str(body.user_email or "").strip().lower(),
            reason=str(body.reason or "").strip(),
            evidence_type=body.evidence_type,
            evidence_ticket_id=str(body.evidence_ticket_id or "").strip(),
            evidence_report_id=str(body.evidence_report_id or "").strip(),
            incident_scope=body.incident_scope,
            incident_laboratory_id=str(body.incident_laboratory_id or "").strip(),
            incident_date=str(body.incident_date or "").strip(),
            incident_start_time=str(body.incident_start_time or "").strip(),
            incident_end_time=str(body.incident_end_time or "").strip(),
            asset_id=str(body.asset_id or "").strip(),
            related_reservation_id=str(body.related_reservation_id or "").strip(),
            starts_at=starts_at,
            ends_at=ends_at,
            notes=str(body.notes or "").strip(),
            status="scheduled",
            is_active=False,
            email_sent=bool(email_sent),
            created_at=now_iso,
            updated_at=now_iso,
            created_by=actor_user_id,
            created_by_name=actor_name,
            lifted_at="",
            lifted_by="",
            lifted_by_name="",
            lift_reason="",
        )
        hydrated = self._hydrate(record)

        with self._lock:
            self._items.append(hydrated)

        self._persist(hydrated, operation="create")
        return hydrated

    def update_email_delivery(self, penalty_id: str, *, email_sent: bool) -> PenaltyResponse | None:
        with self._lock:
            for index, item in enumerate(self._items):
                if item.id != penalty_id:
                    continue
                updated = self._hydrate(
                    item.model_copy(
                        update={
                            "email_sent": bool(email_sent),
                            "updated_at": _utcnow_iso(),
                        }
                    )
                )
                self._items[index] = updated
                self._persist(updated)
                return updated
        return None

    def lift(self, penalty_id: str, *, current_user: dict, lift_reason: str = "") -> PenaltyResponse | None:
        actor_user_id = str(current_user.get("user_id") or "").strip()
        actor_name = str(current_user.get("name") or current_user.get("username") or "Administrador").strip()
        now_iso = _utcnow_iso()

        with self._lock:
            for index, item in enumerate(self._items):
                if item.id != penalty_id:
                    continue

                updated = self._hydrate(
                    item.model_copy(
                        update={
                            "lifted_at": now_iso,
                            "lifted_by": actor_user_id,
                            "lifted_by_name": actor_name,
                            "lift_reason": str(lift_reason or "").strip(),
                            "updated_at": now_iso,
                        }
                    )
                )
                self._items[index] = updated
                self._persist(updated)
                return updated

        return None


penalty_store = PenaltyStore()
