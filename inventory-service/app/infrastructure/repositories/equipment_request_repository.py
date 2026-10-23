from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock

from app.core.config import settings
from app.infrastructure.pocketbase_base import PocketBaseClient as BasePocketBaseClient
from app.infrastructure.pocketbase_client import PocketBaseClient as AdminPocketBaseClient
from app.schemas.equipment_request import EquipmentRequestCreate, EquipmentRequestResponse
from app.schemas.loan_record import LoanRecordCreate, LoanRecordReturn


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _escape_filter_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


_ACTIVE_STATUSES = {"pending", "approved"}


class EquipmentRequestRepository:
    """Solicitudes de prestamo de equipo (p. ej. de un docente para su clase).

    Sigue el mismo patron admin que ``loan_record_repository``: coleccion propia
    ``inventory_equipment_requests_v2`` gestionada con el cliente de superusuario.
    Al aprobar una solicitud puntual (``once``) se genera el prestamo real; las
    solicitudes semanales quedan autorizadas y el encargado entrega cada semana.
    """

    def __init__(self, client: BasePocketBaseClient, *, asset_repo, loan_record_repo) -> None:
        self._client = client
        self._asset_repo = asset_repo
        self._loan_record_repo = loan_record_repo
        self._collection = settings.pb_equipment_requests_collection
        self._admin_client = AdminPocketBaseClient(
            base_url=settings.pocketbase_url,
            auth_token=settings.pocketbase_auth_token,
            auth_identity=settings.pocketbase_auth_identity,
            auth_password=settings.pocketbase_auth_password,
            auth_collection=settings.pocketbase_auth_collection,
            timeout_seconds=settings.pocketbase_timeout_seconds,
        )
        self._collection_ready = False
        self._collection_lock = Lock()

    def _ensure_collection(self) -> None:
        if self._collection_ready or not self._admin_client.enabled:
            return
        with self._collection_lock:
            if self._collection_ready:
                return
            self._admin_client.ensure_collection(
                self._collection,
                [
                    {"name": "asset_id", "type": "text", "required": True, "max": 80},
                    {"name": "asset_name", "type": "text", "required": False, "max": 180},
                    {"name": "asset_serial_number", "type": "text", "required": False, "max": 160},
                    {"name": "laboratory_id", "type": "text", "required": False, "max": 80},
                    {"name": "laboratory_name", "type": "text", "required": False, "max": 180},
                    {"name": "requested_by", "type": "text", "required": True, "max": 120},
                    {"name": "requested_by_name", "type": "text", "required": False, "max": 180},
                    {"name": "requested_by_email", "type": "text", "required": False, "max": 180},
                    {"name": "requested_by_role", "type": "text", "required": False, "max": 80},
                    {"name": "purpose", "type": "text", "required": False, "max": 4000},
                    {"name": "notes", "type": "text", "required": False, "max": 4000},
                    {"name": "requested_for", "type": "text", "required": False, "max": 300},
                    {"name": "status", "type": "text", "required": True, "max": 20},
                    {"name": "lab_reservation_id", "type": "text", "required": False, "max": 80},
                    {"name": "loan_record_id", "type": "text", "required": False, "max": 80},
                    {"name": "recurrence", "type": "text", "required": False, "max": 20},
                    {"name": "recurrence_end_date", "type": "text", "required": False, "max": 30},
                    {"name": "recurrence_group_id", "type": "text", "required": False, "max": 80},
                    {"name": "decided_by", "type": "text", "required": False, "max": 160},
                    {"name": "decided_at", "type": "date", "required": False},
                    {"name": "requested_at", "type": "date", "required": True},
                ],
            )
            self._collection_ready = True

    def _to_response(self, record: dict) -> EquipmentRequestResponse:
        return EquipmentRequestResponse(
            id=record.get("id", ""),
            asset_id=record.get("asset_id", ""),
            asset_name=record.get("asset_name", ""),
            asset_serial_number=record.get("asset_serial_number", ""),
            laboratory_id=record.get("laboratory_id", ""),
            laboratory_name=record.get("laboratory_name", ""),
            requested_by=record.get("requested_by", ""),
            requested_by_name=record.get("requested_by_name", ""),
            requested_by_email=record.get("requested_by_email", ""),
            requested_by_role=record.get("requested_by_role", ""),
            purpose=record.get("purpose", ""),
            notes=record.get("notes", ""),
            requested_for=record.get("requested_for", ""),
            status=record.get("status", "pending"),
            lab_reservation_id=record.get("lab_reservation_id", ""),
            loan_record_id=record.get("loan_record_id", ""),
            recurrence=record.get("recurrence", ""),
            recurrence_end_date=record.get("recurrence_end_date", ""),
            recurrence_group_id=record.get("recurrence_group_id", ""),
            decided_by=record.get("decided_by", ""),
            decided_at=record.get("decided_at", ""),
            requested_at=record.get("requested_at", ""),
            created=record.get("created", ""),
            updated=record.get("updated", ""),
        )

    def list_all(
        self,
        *,
        status_filter: str | None = None,
        requested_by: str | None = None,
        recurrence_group_id: str | None = None,
        lab_reservation_id: str | None = None,
        lab_ids: list[str] | None = None,
    ) -> list[EquipmentRequestResponse]:
        self._ensure_collection()
        clauses: list[str] = []
        if status_filter:
            clauses.append(f'status="{_escape_filter_value(status_filter)}"')
        if requested_by:
            clauses.append(f'requested_by="{_escape_filter_value(requested_by)}"')
        if recurrence_group_id:
            clauses.append(f'recurrence_group_id="{_escape_filter_value(recurrence_group_id)}"')
        if lab_reservation_id:
            clauses.append(f'lab_reservation_id="{_escape_filter_value(lab_reservation_id)}"')
        if lab_ids is not None:
            ids = [str(x).strip() for x in lab_ids if str(x or "").strip()]
            if not ids:
                clauses.append('id="__no_accessible_labs__"')
            else:
                quoted = " || ".join(f'laboratory_id="{_escape_filter_value(v)}"' for v in ids)
                clauses.append(f"({quoted})")
        filter_expression = " && ".join(clauses) if clauses else None
        # Las colecciones *_v2 no tienen campo system `created`; ordenamos por la
        # fecha propia de la solicitud.
        records = self._admin_client.list_records(
            self._collection,
            sort="-requested_at",
            filter=filter_expression,
            per_page=200,
        )
        return [self._to_response(r) for r in records]

    def get_by_id(self, request_id: str) -> EquipmentRequestResponse | None:
        self._ensure_collection()
        record = self._admin_client.get_record(self._collection, request_id)
        if record is None:
            return None
        return self._to_response(record)

    def create(self, body: EquipmentRequestCreate, *, current_user: dict) -> EquipmentRequestResponse:
        asset = self._asset_repo.get_by_id(body.asset_id)
        if asset is None:
            raise ValueError("Equipo no encontrado")

        requested_by = str(current_user.get("user_id") or current_user.get("username") or "").strip()
        if not requested_by:
            raise ValueError("No se pudo identificar al usuario autenticado para registrar la solicitud")

        recurrence = str(body.recurrence or "").strip().lower()
        if recurrence not in {"once", "weekly"}:
            recurrence = "once"

        payload = {
            "asset_id": asset.id,
            "asset_name": asset.name,
            "asset_serial_number": asset.serial_number or "",
            "laboratory_id": str(asset.laboratory_id or body.laboratory_id or ""),
            "laboratory_name": asset.laboratory_name or "",
            "requested_by": requested_by,
            "requested_by_name": str(body.requested_by_name or current_user.get("username") or "").strip(),
            "requested_by_email": str(body.requested_by_email or "").strip(),
            "requested_by_role": str(current_user.get("role") or "").strip(),
            "purpose": str(body.purpose or "").strip(),
            "notes": str(body.notes or "").strip(),
            "requested_for": str(body.requested_for or "").strip(),
            "status": "pending",
            "lab_reservation_id": str(body.lab_reservation_id or "").strip(),
            "recurrence": recurrence,
            "recurrence_end_date": str(body.recurrence_end_date or "").strip() if recurrence == "weekly" else "",
            "recurrence_group_id": str(body.recurrence_group_id or "").strip(),
            "requested_at": _utcnow_iso(),
        }

        self._ensure_collection()
        record = self._admin_client.create_record(self._collection, payload)
        return self._to_response(record)

    def update_status(
        self,
        request_id: str,
        new_status: str,
        *,
        current_user: dict,
        notes: str | None = None,
    ) -> EquipmentRequestResponse:
        existing = self.get_by_id(request_id)
        if existing is None:
            raise ValueError("Solicitud de equipo no encontrada")

        normalized = str(new_status or "").strip().lower()
        if normalized not in {"pending", "approved", "rejected", "cancelled", "delivered", "returned"}:
            raise ValueError("Estado invalido para la solicitud de equipo")

        if existing.status == normalized:
            return existing

        actor = str(current_user.get("username") or current_user.get("user_id") or "sistema")
        now_iso = _utcnow_iso()
        is_weekly = str(existing.recurrence or "").strip().lower() == "weekly"
        loan_record_id = existing.loan_record_id

        # Aprobacion: la solicitud puntual genera el prestamo real de una vez.
        # La solicitud semanal solo queda autorizada (el encargado entrega cada
        # semana con el flujo normal de prestamos).
        if normalized == "approved" and existing.status not in {"approved"}:
            if not is_weekly and not loan_record_id:
                loan = self._loan_record_repo.create(
                    LoanRecordCreate(
                        asset_id=existing.asset_id,
                        borrower_id=existing.requested_by,
                        borrower_name=existing.requested_by_name or existing.requested_by,
                        borrower_email=existing.requested_by_email,
                        borrower_role=existing.requested_by_role,
                        purpose=existing.purpose,
                        notes=existing.notes,
                    ),
                    current_user=current_user,
                )
                loan_record_id = loan.id

        # Rechazo / cancelacion de una solicitud puntual ya aprobada: se devuelve
        # el prestamo generado para liberar el equipo.
        if normalized in {"rejected", "cancelled"} and existing.status == "approved" and loan_record_id:
            try:
                self._loan_record_repo.return_loan(
                    loan_record_id,
                    LoanRecordReturn(return_condition="ok", return_notes="Solicitud de equipo cancelada"),
                    current_user=current_user,
                )
            except ValueError:
                # El prestamo ya podia estar devuelto; no bloqueamos la cancelacion.
                pass

        update_payload = {
            "status": normalized,
            "decided_by": actor,
            "decided_at": now_iso,
            "loan_record_id": loan_record_id or "",
        }
        if notes is not None:
            update_payload["notes"] = notes

        self._ensure_collection()
        record = self._admin_client.update_record(self._collection, request_id, update_payload)
        return self._to_response(record)
