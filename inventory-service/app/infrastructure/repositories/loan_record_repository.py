from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock

from app.core.config import settings
from app.infrastructure.cache_utils import TTLCache
from app.infrastructure.pocketbase_base import PocketBaseClient as BasePocketBaseClient
from app.infrastructure.pocketbase_client import PocketBaseClient as AdminPocketBaseClient
from app.schemas.asset import AssetUpdate
from app.schemas.asset_maintenance import AssetMaintenanceTicketCreate
from app.schemas.loan_record import (
    LoanDashboardResponse,
    LoanRecordCreate,
    LoanRecordResponse,
    LoanRecordReturn,
    PaginatedLoanRecordResponse,
)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _escape_filter_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


class LoanRecordRepository:
    def __init__(self, client: BasePocketBaseClient, *, asset_repo, asset_maintenance_repo) -> None:
        self._client = client
        self._asset_repo = asset_repo
        self._asset_maintenance_repo = asset_maintenance_repo
        self._collection = settings.pb_loan_records_collection
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
        self._records_cache = TTLCache[list[dict]](ttl_seconds=3.0)

    def _invalidate_cache(self) -> None:
        self._records_cache.invalidate()

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
                    {"name": "asset_name", "type": "text", "required": True, "max": 180},
                    {"name": "asset_serial_number", "type": "text", "required": False, "max": 160},
                    {"name": "laboratory_id", "type": "text", "required": False, "max": 80},
                    {"name": "laboratory_name", "type": "text", "required": False, "max": 180},
                    {"name": "borrower_id", "type": "text", "required": True, "max": 120},
                    {"name": "borrower_name", "type": "text", "required": True, "max": 180},
                    {"name": "borrower_email", "type": "text", "required": False, "max": 180},
                    {"name": "borrower_role", "type": "text", "required": False, "max": 80},
                    {"name": "purpose", "type": "text", "required": False, "max": 4000},
                    {"name": "notes", "type": "text", "required": False, "max": 4000},
                    {"name": "status", "type": "text", "required": True, "max": 20},
                    {"name": "loaned_by", "type": "text", "required": True, "max": 160},
                    {"name": "returned_by", "type": "text", "required": False, "max": 160},
                    {"name": "loaned_at", "type": "date", "required": True},
                    {"name": "due_at", "type": "date", "required": False},
                    {"name": "returned_at", "type": "date", "required": False},
                    {"name": "return_condition", "type": "text", "required": False, "max": 30},
                    {"name": "return_notes", "type": "text", "required": False, "max": 4000},
                    {"name": "incident_notes", "type": "text", "required": False, "max": 4000},
                ],
            )
            self._collection_ready = True

    def _to_response(self, record: dict) -> LoanRecordResponse:
        return LoanRecordResponse(
            id=record.get("id", ""),
            asset_id=record.get("asset_id", ""),
            asset_name=record.get("asset_name", ""),
            asset_serial_number=record.get("asset_serial_number", ""),
            laboratory_id=record.get("laboratory_id", ""),
            laboratory_name=record.get("laboratory_name", ""),
            borrower_id=record.get("borrower_id", ""),
            borrower_name=record.get("borrower_name", ""),
            borrower_email=record.get("borrower_email", ""),
            borrower_role=record.get("borrower_role", ""),
            purpose=record.get("purpose", ""),
            notes=record.get("notes", ""),
            status=record.get("status", "active"),
            loaned_by=record.get("loaned_by", ""),
            returned_by=record.get("returned_by", ""),
            loaned_at=record.get("loaned_at", ""),
            due_at=record.get("due_at", ""),
            returned_at=record.get("returned_at", ""),
            return_condition=record.get("return_condition", "ok"),
            return_notes=record.get("return_notes", ""),
            incident_notes=record.get("incident_notes", ""),
            created=record.get("created", ""),
            updated=record.get("updated", ""),
        )

    def _build_filter(
        self,
        *,
        status_filter: str | None = None,
        asset_id: str | None = None,
        serial_number: str | None = None,
        lab_ids: list[str] | None = None,
    ) -> str | None:
        filter_clauses: list[str] = []
        if status_filter:
            filter_clauses.append(f'status="{_escape_filter_value(status_filter)}"')
        if asset_id:
            filter_clauses.append(f'asset_id="{_escape_filter_value(str(asset_id).strip())}"')
        if serial_number:
            filter_clauses.append(f'asset_serial_number~"{_escape_filter_value(str(serial_number).strip())}"')
        if lab_ids is not None:
            ids = [str(lab_id).strip() for lab_id in lab_ids if str(lab_id or "").strip()]
            if not ids:
                # User has no accessible labs: return a filter that matches nothing.
                filter_clauses.append('id="__no_accessible_labs__"')
            else:
                quoted = " || ".join(f'laboratory_id="{_escape_filter_value(value)}"' for value in ids)
                filter_clauses.append(f'({quoted})')
        return " && ".join(filter_clauses) if filter_clauses else None

    def _list_raw(self, *, filter_expression: str | None = None) -> list[dict]:
        self._ensure_collection()
        cache_key = ("raw", filter_expression or "")
        return self._records_cache.get_or_set(
            cache_key,
            lambda: self._admin_client.list_records(
                self._collection,
                sort="-loaned_at",
                filter=filter_expression,
                per_page=200,
            ),
        )

    def _list_page_raw(self, *, page: int, per_page: int, filter_expression: str | None) -> dict:
        self._ensure_collection()
        cache_key = ("page", page, per_page, filter_expression or "")
        return self._records_cache.get_or_set(
            cache_key,
            lambda: self._admin_client.list_records_page(
                self._collection,
                page=page,
                per_page=per_page,
                sort="-loaned_at",
                filter=filter_expression,
            ),
        )

    def _count(self, filter_expression: str | None) -> int:
        self._ensure_collection()
        cache_key = ("count", filter_expression or "")
        return self._records_cache.get_or_set(
            cache_key,
            lambda: self._admin_client.count_records(self._collection, filter=filter_expression),
        )

    def list_all(
        self,
        *,
        status_filter: str | None = None,
        asset_id: str | None = None,
        borrower_query: str | None = None,
        serial_number: str | None = None,
        lab_ids: list[str] | None = None,
    ) -> list[LoanRecordResponse]:
        filter_expression = self._build_filter(
            status_filter=status_filter,
            asset_id=asset_id,
            serial_number=serial_number,
            lab_ids=lab_ids,
        )
        items = [self._to_response(record) for record in self._list_raw(filter_expression=filter_expression)]

        if borrower_query:
            needle = str(borrower_query).strip().lower()
            items = [
                item for item in items
                if needle in str(item.borrower_name or "").lower()
                or needle in str(item.borrower_email or "").lower()
                or needle in str(item.borrower_id or "").lower()
            ]

        return items

    def list_paginated(
        self,
        *,
        page: int = 1,
        per_page: int = 50,
        status_filter: str | None = None,
        asset_id: str | None = None,
        borrower_query: str | None = None,
        serial_number: str | None = None,
        lab_ids: list[str] | None = None,
    ) -> PaginatedLoanRecordResponse:
        normalized_page = max(int(page or 1), 1)
        normalized_per_page = max(min(int(per_page or 50), 200), 1)

        # When filtering by borrower text, PocketBase cannot help (multi-field search):
        # fall back to load + filter + slice in Python. Otherwise, paginate server-side.
        if borrower_query:
            full = self.list_all(
                status_filter=status_filter,
                asset_id=asset_id,
                borrower_query=borrower_query,
                serial_number=serial_number,
                lab_ids=lab_ids,
            )
            total_items = len(full)
            total_pages = max((total_items + normalized_per_page - 1) // normalized_per_page, 1) if total_items else 0
            offset = (normalized_page - 1) * normalized_per_page
            page_items = full[offset:offset + normalized_per_page]
            return PaginatedLoanRecordResponse(
                items=page_items,
                page=normalized_page,
                per_page=normalized_per_page,
                total_items=total_items,
                total_pages=total_pages,
            )

        filter_expression = self._build_filter(
            status_filter=status_filter,
            asset_id=asset_id,
            serial_number=serial_number,
            lab_ids=lab_ids,
        )
        page_data = self._list_page_raw(
            page=normalized_page,
            per_page=normalized_per_page,
            filter_expression=filter_expression,
        )
        return PaginatedLoanRecordResponse(
            items=[self._to_response(record) for record in page_data.get("items", [])],
            page=int(page_data.get("page", normalized_page) or normalized_page),
            per_page=int(page_data.get("perPage", normalized_per_page) or normalized_per_page),
            total_items=int(page_data.get("totalItems", 0) or 0),
            total_pages=int(page_data.get("totalPages", 0) or 0),
        )

    def list_for_asset(self, asset_id: str) -> list[LoanRecordResponse]:
        normalized_asset_id = str(asset_id or "").strip()
        if not normalized_asset_id:
            return []
        return self.list_all(asset_id=normalized_asset_id)

    def get_by_id(self, loan_id: str) -> LoanRecordResponse | None:
        self._ensure_collection()
        record = self._admin_client.get_record(self._collection, loan_id)
        if record is None:
            return None
        return self._to_response(record)

    def get_open_for_asset(self, asset_id: str) -> LoanRecordResponse | None:
        for item in self.list_all(status_filter="active", asset_id=asset_id):
            if item.status == "active" and not item.returned_at:
                return item
        return None

    def create(self, body: LoanRecordCreate, *, current_user: dict) -> LoanRecordResponse:
        asset = self._asset_repo.get_by_id(body.asset_id)
        if asset is None:
            raise ValueError("Equipo no encontrado")

        if asset.status == "maintenance":
            raise ValueError("El equipo esta en mantenimiento y no puede prestarse")
        if asset.status == "loaned" or self.get_open_for_asset(asset.id):
            raise ValueError("El equipo ya se encuentra prestado y no puede asignarse nuevamente")
        if asset.status == "damaged":
            raise ValueError("El equipo esta marcado como dañado y debe pasar por mantenimiento antes de un nuevo prestamo")
        if asset.status != "available":
            raise ValueError("El equipo no esta disponible para prestamo")

        actor = str(current_user.get("username") or "encargado")
        now_iso = _utcnow_iso()
        payload = {
            "asset_id": asset.id,
            "asset_name": asset.name,
            "asset_serial_number": asset.serial_number,
            "laboratory_id": asset.laboratory_id,
            "laboratory_name": asset.laboratory_name or "",
            "borrower_id": body.borrower_id.strip(),
            "borrower_name": body.borrower_name.strip(),
            "borrower_email": body.borrower_email.strip().lower(),
            "borrower_role": body.borrower_role.strip(),
            "purpose": body.purpose.strip(),
            "notes": body.notes.strip(),
            "status": "active",
            "loaned_by": actor,
            "loaned_at": now_iso,
            "due_at": str(body.due_at or "").strip(),
            "return_condition": "ok",
        }

        self._ensure_collection()
        record = self._admin_client.create_record(self._collection, payload)
        self._invalidate_cache()
        self._asset_repo.update(
            asset.id,
            AssetUpdate(
                status="loaned",
                status_updated_at=now_iso,
                status_updated_by=actor,
            ),
        )
        return self._to_response(record)

    def return_loan(self, loan_id: str, body: LoanRecordReturn, *, current_user: dict) -> LoanRecordResponse:
        loan = self.get_by_id(loan_id)
        if loan is None:
            raise ValueError("Prestamo no encontrado")
        if loan.status != "active":
            raise ValueError("El prestamo ya fue cerrado y no puede procesarse nuevamente")
        if body.return_condition == "damaged" and not str(body.incident_notes or "").strip():
            raise ValueError("Debes describir el problema cuando marcas una devolucion con daños")

        actor = str(current_user.get("username") or "encargado")
        now_iso = _utcnow_iso()
        updated = self._admin_client.update_record(
            self._collection,
            loan_id,
            {
                "status": "returned",
                "returned_by": actor,
                "returned_at": now_iso,
                "return_condition": body.return_condition,
                "return_notes": str(body.return_notes or "").strip(),
                "incident_notes": str(body.incident_notes or "").strip(),
            },
        )
        self._invalidate_cache()

        if body.return_condition == "damaged":
            try:
                self._asset_maintenance_repo.create(
                    loan.asset_id,
                    AssetMaintenanceTicketCreate(
                        ticket_type="damage",
                        title=f"Daño reportado durante devolucion de {loan.asset_name}",
                        description=str(body.incident_notes or "").strip(),
                        severity="high",
                        evidence_report_id=loan.id,
                    ),
                    current_user=current_user,
                )
            except ValueError:
                self._asset_repo.update(
                    loan.asset_id,
                    AssetUpdate(
                        status="maintenance",
                        status_updated_at=now_iso,
                        status_updated_by=actor,
                    ),
                )
        else:
            self._asset_repo.update(
                loan.asset_id,
                AssetUpdate(
                    status="available",
                    status_updated_at=now_iso,
                    status_updated_by=actor,
                ),
            )

        return self._to_response(updated)

    def get_dashboard(
        self,
        *,
        page: int = 1,
        per_page: int = 50,
        lab_ids: list[str] | None = None,
    ) -> LoanDashboardResponse:
        normalized_page = max(int(page or 1), 1)
        normalized_per_page = max(min(int(per_page or 50), 200), 1)

        base_filter = self._build_filter(lab_ids=lab_ids)
        active_filter = self._build_filter(status_filter="active", lab_ids=lab_ids)
        returned_filter = self._build_filter(status_filter="returned", lab_ids=lab_ids)
        damaged_clauses = ['status="returned"', 'return_condition="damaged"']
        if lab_ids is not None:
            ids = [str(lab_id).strip() for lab_id in lab_ids if str(lab_id or "").strip()]
            if not ids:
                damaged_clauses.append('id="__no_accessible_labs__"')
            else:
                quoted = " || ".join(f'laboratory_id="{_escape_filter_value(value)}"' for value in ids)
                damaged_clauses.append(f'({quoted})')
        damaged_filter = " && ".join(damaged_clauses)

        total_records = self._count(base_filter)
        active_count = self._count(active_filter)
        returned_count = self._count(returned_filter)
        damaged_count = self._count(damaged_filter)

        active_page = self._list_page_raw(
            page=normalized_page,
            per_page=normalized_per_page,
            filter_expression=active_filter,
        )
        active_loans = [self._to_response(record) for record in active_page.get("items", [])]
        active_total_pages = int(active_page.get("totalPages", 0) or 0)

        return LoanDashboardResponse(
            total_records=total_records,
            active_count=active_count,
            returned_count=returned_count,
            damaged_returns_count=damaged_count,
            active_loans=active_loans,
            active_loans_page=normalized_page,
            active_loans_per_page=normalized_per_page,
            active_loans_total_pages=active_total_pages,
        )
