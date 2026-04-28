from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from threading import Lock

from app.core.config import settings
from app.infrastructure.pocketbase_admin import PocketBaseAdminClient
from app.schemas.lab_access_session import LabAccessSessionResponse
from app.schemas.lab_reservation import OccupancyDashboardResponse, OccupancyLabSummary, OccupancySessionResponse


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class LabAccessSessionRepository:
    def __init__(self) -> None:
        self._collection = settings.pb_lab_access_sessions_collection
        self._client = PocketBaseAdminClient(
            base_url=settings.pocketbase_url,
            auth_identity=settings.pocketbase_auth_identity,
            auth_password=settings.pocketbase_auth_password,
            auth_collection=settings.pocketbase_auth_collection,
            timeout_seconds=settings.pocketbase_timeout_seconds,
        )
        self._collection_ready = False
        self._lock = Lock()

    def _ensure_collection(self) -> None:
        if self._collection_ready or not self._client.enabled:
            return
        with self._lock:
            if self._collection_ready:
                return
            self._client.ensure_collection(
                self._collection,
                [
                    {"name": "reservation_id", "type": "text", "required": True, "max": 120},
                    {"name": "laboratory_id", "type": "text", "required": True, "max": 80},
                    {"name": "requested_by", "type": "text", "required": True, "max": 120},
                    {"name": "occupant_name", "type": "text", "required": False, "max": 160},
                    {"name": "occupant_email", "type": "text", "required": False, "max": 180},
                    {"name": "station_label", "type": "text", "required": False, "max": 80},
                    {"name": "purpose", "type": "text", "required": False, "max": 4000},
                    {"name": "start_at", "type": "date", "required": True},
                    {"name": "end_at", "type": "date", "required": True},
                    {"name": "check_in_at", "type": "date", "required": True},
                    {"name": "check_out_at", "type": "date", "required": False},
                    {"name": "status", "type": "text", "required": True, "max": 20},
                    {"name": "is_walk_in", "type": "bool", "required": False},
                    {"name": "recorded_by", "type": "text", "required": False, "max": 160},
                    {"name": "notes", "type": "text", "required": False, "max": 2000},
                ],
            )
            self._collection_ready = True

    def _to_response(self, record: dict) -> LabAccessSessionResponse:
        return LabAccessSessionResponse(
            id=record.get("id", ""),
            reservation_id=record.get("reservation_id", ""),
            laboratory_id=record.get("laboratory_id", ""),
            requested_by=record.get("requested_by", ""),
            occupant_name=record.get("occupant_name", ""),
            occupant_email=record.get("occupant_email", ""),
            station_label=record.get("station_label", ""),
            purpose=record.get("purpose", ""),
            start_at=record.get("start_at", ""),
            end_at=record.get("end_at", ""),
            check_in_at=record.get("check_in_at", ""),
            check_out_at=record.get("check_out_at", ""),
            status=record.get("status", "open"),
            is_walk_in=bool(record.get("is_walk_in", False)),
            recorded_by=record.get("recorded_by", ""),
            notes=record.get("notes", ""),
            created=record.get("created", ""),
            updated=record.get("updated", ""),
        )

    def list_all(self) -> list[LabAccessSessionResponse]:
        self._ensure_collection()
        return [self._to_response(record) for record in self._client.list_records(self._collection, sort="-check_in_at")]

    def list_by_reservation_ids(self, reservation_ids: list[str]) -> list[LabAccessSessionResponse]:
        self._ensure_collection()
        ids = [str(rid).strip() for rid in reservation_ids if str(rid or "").strip()]
        if not ids:
            return []
        escaped = [str(rid).replace("\\", "\\\\").replace('"', '\\"') for rid in ids]
        filter_expression = " || ".join(f'reservation_id="{rid}"' for rid in escaped)
        records = self._client.list_records(self._collection, sort="-check_in_at", filter=filter_expression)
        return [self._to_response(record) for record in records]

    def list_active_sessions(self, laboratory_id: str | None = None) -> list[LabAccessSessionResponse]:
        self._ensure_collection()
        clauses = ['status="open"', 'check_out_at=""']
        if laboratory_id:
            escaped_lab = str(laboratory_id).replace("\\", "\\\\").replace('"', '\\"')
            clauses.append(f'laboratory_id="{escaped_lab}"')
        records = self._client.list_records(
            self._collection,
            sort="-check_in_at",
            filter=" && ".join(clauses),
        )
        return [self._to_response(record) for record in records]

    def get_open_by_reservation(self, reservation_id: str) -> LabAccessSessionResponse | None:
        self._ensure_collection()
        normalized = str(reservation_id or "").strip()
        if not normalized:
            return None
        escaped = normalized.replace("\\", "\\\\").replace('"', '\\"')
        records = self._client.list_records(
            self._collection,
            sort="-check_in_at",
            filter=f'reservation_id="{escaped}" && status="open" && check_out_at=""',
            per_page=1,
        )
        if not records:
            return None
        return self._to_response(records[0])

    def create(
        self,
        *,
        reservation_id: str,
        laboratory_id: str,
        requested_by: str,
        occupant_name: str,
        occupant_email: str,
        station_label: str,
        purpose: str,
        start_at: str,
        end_at: str,
        is_walk_in: bool,
        recorded_by: str,
        notes: str = "",
    ) -> LabAccessSessionResponse:
        self._ensure_collection()
        record = self._client.create_record(
            self._collection,
            {
                "reservation_id": reservation_id,
                "laboratory_id": laboratory_id,
                "requested_by": requested_by,
                "occupant_name": occupant_name,
                "occupant_email": occupant_email,
                "station_label": station_label,
                "purpose": purpose,
                "start_at": start_at,
                "end_at": end_at,
                "check_in_at": _utcnow_iso(),
                "status": "open",
                "is_walk_in": bool(is_walk_in),
                "recorded_by": recorded_by,
                "notes": notes,
            },
        )
        return self._to_response(record)

    def close(self, session_id: str) -> LabAccessSessionResponse | None:
        self._ensure_collection()
        record = self._client.get_record(self._collection, session_id)
        if record is None:
            return None
        updated = self._client.update_record(
            self._collection,
            session_id,
            {
                "check_out_at": _utcnow_iso(),
                "status": "closed",
            },
        )
        return self._to_response(updated)

    def enrich_reservation(self, reservation) -> dict:
        enriched = self.enrich_reservations([reservation])
        if enriched:
            return enriched[0]
        session = None
        return {
            **reservation.model_dump(),
            "requested_by_name": session.occupant_name if session else "",
            "requested_by_email": session.occupant_email if session else "",
            "station_label": session.station_label if session else "",
            "check_in_at": session.check_in_at if session else "",
            "check_out_at": session.check_out_at if session else "",
            "is_walk_in": bool(session.is_walk_in) if session else False,
        }

    def enrich_reservations(self, reservations: list) -> list[dict]:
        if not reservations:
            return []

        reservation_ids = [str(item.id) for item in reservations if getattr(item, "id", "")]
        if not reservation_ids:
            return [item.model_dump() for item in reservations]

        sessions = self.list_by_reservation_ids(reservation_ids)
        indexed_sessions: dict[str, LabAccessSessionResponse] = {}
        for session in sessions:
            reservation_id = str(session.reservation_id or "")
            if reservation_id in indexed_sessions:
                continue
            indexed_sessions[reservation_id] = session

        open_sessions = {
            str(session.reservation_id or ""): session
            for session in sessions
            if session.status == "open" and not session.check_out_at
        }

        enriched_items: list[dict] = []
        for reservation in reservations:
            session = open_sessions.get(str(reservation.id)) or indexed_sessions.get(str(reservation.id))
            enriched_items.append(
                {
                    **reservation.model_dump(),
                    "requested_by_name": session.occupant_name if session else reservation.requested_by_name,
                    "requested_by_email": session.occupant_email if session else reservation.requested_by_email,
                    "station_label": session.station_label if session else reservation.station_label,
                    "check_in_at": session.check_in_at if session else reservation.check_in_at,
                    "check_out_at": session.check_out_at if session else reservation.check_out_at,
                    "is_walk_in": bool(session.is_walk_in) if session else bool(reservation.is_walk_in),
                }
            )

        return enriched_items

    def get_dashboard(self, *, laboratory_id: str | None = None) -> OccupancyDashboardResponse:
        active_sessions = self.list_active_sessions(laboratory_id=laboratory_id)

        counts = Counter(item.laboratory_id for item in active_sessions)
        return OccupancyDashboardResponse(
            current_occupancy=len(active_sessions),
            active_sessions=[
                OccupancySessionResponse(
                    reservation_id=item.reservation_id,
                    laboratory_id=item.laboratory_id,
                    requested_by=item.requested_by,
                    requested_by_name=item.occupant_name,
                    requested_by_email=item.occupant_email,
                    station_label=item.station_label,
                    check_in_at=item.check_in_at,
                    start_at=item.start_at,
                    end_at=item.end_at,
                    is_walk_in=item.is_walk_in,
                    purpose=item.purpose,
                )
                for item in active_sessions
            ],
            lab_breakdown=[
                OccupancyLabSummary(laboratory_id=lab_id, occupancy_count=count)
                for lab_id, count in sorted(counts.items())
            ],
        )
