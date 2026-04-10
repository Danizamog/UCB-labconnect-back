from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any

import httpx

from app.core.config import settings
from app.infrastructure.cache_utils import TTLCache
from app.infrastructure.pocketbase_base import PocketBaseClient as BasePocketBaseClient
from app.infrastructure.pocketbase_client import PocketBaseClient as AdminPocketBaseClient
from app.schemas.asset import AssetResponse, AssetUpdate
from app.schemas.asset_maintenance import (
    AssetMaintenanceTicketClose,
    AssetMaintenanceTicketCreate,
    AssetMaintenanceTicketResponse,
    AssetResponsibilityFlagResponse,
)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _escape_filter_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


class AssetMaintenanceRepository:
    def __init__(self, client: BasePocketBaseClient, *, asset_repo) -> None:
        self._client = client
        self._asset_repo = asset_repo
        self._collection = settings.pb_asset_maintenance_tickets_collection
        self._loan_collection = settings.pb_loan_records_collection
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
        self._records_cache = TTLCache[list[dict[str, Any]]](ttl_seconds=3.0)

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
                    {"name": "asset_name", "type": "text", "required": True, "max": 160},
                    {"name": "ticket_type", "type": "text", "required": True, "max": 20},
                    {"name": "title", "type": "text", "required": True, "max": 160},
                    {"name": "description", "type": "text", "required": True, "max": 4000},
                    {"name": "severity", "type": "text", "required": True, "max": 20},
                    {"name": "evidence_report_id", "type": "text", "required": False, "max": 120},
                    {"name": "status", "type": "text", "required": True, "max": 20},
                    {"name": "reported_at", "type": "date", "required": True},
                    {"name": "reported_by", "type": "text", "required": True, "max": 160},
                    {"name": "resolved_at", "type": "date", "required": False},
                    {"name": "resolved_by", "type": "text", "required": False, "max": 160},
                    {"name": "resolution_notes", "type": "text", "required": False, "max": 4000},
                    {"name": "asset_status_before", "type": "text", "required": False, "max": 40},
                    {"name": "asset_status_after_open", "type": "text", "required": False, "max": 40},
                    {"name": "asset_status_after_close", "type": "text", "required": False, "max": 40},
                    {"name": "related_loan_id", "type": "text", "required": False, "max": 120},
                    {"name": "related_loan_status", "type": "text", "required": False, "max": 40},
                    {"name": "related_loaned_at", "type": "date", "required": False},
                    {"name": "responsible_borrower_name", "type": "text", "required": False, "max": 160},
                    {"name": "responsible_borrower_email", "type": "text", "required": False, "max": 180},
                    {"name": "responsible_borrower_role", "type": "text", "required": False, "max": 80},
                    {"name": "is_responsibility_flagged", "type": "bool", "required": False},
                ],
            )
            self._collection_ready = True

    def _to_response(self, record: dict[str, Any]) -> AssetMaintenanceTicketResponse:
        return AssetMaintenanceTicketResponse(
            id=record.get("id", ""),
            asset_id=record.get("asset_id", ""),
            asset_name=record.get("asset_name", ""),
            ticket_type=record.get("ticket_type", "maintenance"),
            title=record.get("title", ""),
            description=record.get("description", ""),
            severity=record.get("severity", "medium"),
            evidence_report_id=record.get("evidence_report_id", ""),
            status=record.get("status", "open"),
            reported_at=record.get("reported_at", ""),
            reported_by=record.get("reported_by", ""),
            resolved_at=record.get("resolved_at", ""),
            resolved_by=record.get("resolved_by", ""),
            resolution_notes=record.get("resolution_notes", ""),
            asset_status_before=record.get("asset_status_before", ""),
            asset_status_after_open=record.get("asset_status_after_open", ""),
            asset_status_after_close=record.get("asset_status_after_close", ""),
            related_loan_id=record.get("related_loan_id", ""),
            related_loan_status=record.get("related_loan_status", ""),
            related_loaned_at=record.get("related_loaned_at", ""),
            responsible_borrower_name=record.get("responsible_borrower_name", ""),
            responsible_borrower_email=record.get("responsible_borrower_email", ""),
            responsible_borrower_role=record.get("responsible_borrower_role", ""),
            is_responsibility_flagged=bool(record.get("is_responsibility_flagged", False)),
            created=record.get("created", ""),
            updated=record.get("updated", ""),
        )

    def _list_raw(self, *, filter_expression: str | None = None) -> list[dict[str, Any]]:
        self._ensure_collection()
        cache_key = ("raw", filter_expression or "")
        return self._records_cache.get_or_set(
            cache_key,
            lambda: self._admin_client.list_records(
                self._collection,
                sort="-reported_at",
                filter=filter_expression,
                per_page=200,
            ),
        )

    def list_all(self, *, status_filter: str | None = None) -> list[AssetMaintenanceTicketResponse]:
        filter_expression = f'status="{_escape_filter_value(status_filter)}"' if status_filter else None
        return [self._to_response(record) for record in self._list_raw(filter_expression=filter_expression)]

    def list_for_asset(self, asset_id: str) -> list[AssetMaintenanceTicketResponse]:
        normalized_asset_id = str(asset_id or "").strip()
        if not normalized_asset_id:
            return []
        filter_expression = f'asset_id="{_escape_filter_value(normalized_asset_id)}"'
        return [self._to_response(record) for record in self._list_raw(filter_expression=filter_expression)]

    def get_by_id(self, ticket_id: str) -> AssetMaintenanceTicketResponse | None:
        self._ensure_collection()
        record = self._admin_client.get_record(self._collection, ticket_id)
        if record is None:
            return None
        return self._to_response(record)

    def _get_asset_record(self, asset_id: str) -> dict[str, Any] | None:
        try:
            record = self._client.request("GET", f"/api/collections/asset/records/{asset_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(record, dict):
            return None
        return record

    def _find_latest_related_loan(self, asset_id: str, *, asset_source_id: str = "") -> dict[str, Any] | None:
        if not self._admin_client.enabled:
            return None

        loan_filter_clauses = [f'asset_id="{_escape_filter_value(str(asset_id or "").strip())}"']
        if asset_source_id:
            loan_filter_clauses.append(f'asset_id="{_escape_filter_value(str(asset_source_id).strip())}"')

        latest_match: dict[str, Any] | None = None
        for clause in loan_filter_clauses:
            matches = self._admin_client.list_records(
                self._loan_collection,
                sort="-loaned_at",
                filter=clause,
                per_page=1,
                max_items=1,
            )
            if matches:
                candidate = matches[0]
                if latest_match is None or str(candidate.get("loaned_at") or "") > str(latest_match.get("loaned_at") or ""):
                    latest_match = candidate

        return latest_match

    def _find_open_ticket_for_asset(self, asset_id: str) -> AssetMaintenanceTicketResponse | None:
        for item in self.list_for_asset(asset_id):
            if item.status == "open":
                return item
        return None

    def create(self, asset_id: str, body: AssetMaintenanceTicketCreate, *, current_user: dict) -> AssetMaintenanceTicketResponse:
        asset = self._asset_repo.get_by_id(asset_id)
        if asset is None:
            raise ValueError("Equipo no encontrado")

        if self._find_open_ticket_for_asset(asset_id):
            raise ValueError("El equipo ya tiene un ticket de mantenimiento activo")

        asset_record = self._get_asset_record(asset_id) or {}
        asset_source_id = str(asset_record.get("source_id") or "").strip()
        latest_loan = self._find_latest_related_loan(asset_id, asset_source_id=asset_source_id)
        actor = str(current_user.get("username") or "encargado")
        now_iso = _utcnow_iso()

        payload = {
            "asset_id": asset.id,
            "asset_name": asset.name,
            "ticket_type": body.ticket_type,
            "title": body.title.strip(),
            "description": body.description.strip(),
            "severity": body.severity,
            "evidence_report_id": str(body.evidence_report_id or "").strip(),
            "status": "open",
            "reported_at": now_iso,
            "reported_by": actor,
            "asset_status_before": asset.status,
            "asset_status_after_open": "maintenance",
            "asset_status_after_close": "available",
            "related_loan_id": str(latest_loan.get("id") or "") if latest_loan else "",
            "related_loan_status": str(latest_loan.get("status") or "") if latest_loan else "",
            "related_loaned_at": str(latest_loan.get("loaned_at") or "") if latest_loan else "",
            "responsible_borrower_name": str(latest_loan.get("borrower_name") or "") if latest_loan else "",
            "responsible_borrower_email": str(latest_loan.get("borrower_email") or "") if latest_loan else "",
            "responsible_borrower_role": str(latest_loan.get("borrower_role") or "") if latest_loan else "",
            "is_responsibility_flagged": bool(latest_loan and body.ticket_type == "damage"),
        }

        self._ensure_collection()
        record = self._admin_client.create_record(self._collection, payload)
        self._invalidate_cache()
        self._asset_repo.update(
            asset_id,
            AssetUpdate(
                status="maintenance",
                status_updated_at=now_iso,
                status_updated_by=actor,
            ),
        )
        return self._to_response(record)

    def close(self, ticket_id: str, body: AssetMaintenanceTicketClose, *, current_user: dict) -> AssetMaintenanceTicketResponse:
        ticket = self.get_by_id(ticket_id)
        if ticket is None:
            raise ValueError("Ticket no encontrado")
        if ticket.status != "open":
            raise ValueError("El ticket ya fue cerrado y no puede modificarse")

        actor = str(current_user.get("username") or "encargado")
        now_iso = _utcnow_iso()
        updated = self._admin_client.update_record(
            self._collection,
            ticket_id,
            {
                "status": "closed",
                "resolved_at": now_iso,
                "resolved_by": actor,
                "resolution_notes": body.resolution_notes.strip(),
            },
        )
        self._invalidate_cache()
        self._asset_repo.update(
            ticket.asset_id,
            AssetUpdate(
                status="available",
                status_updated_at=now_iso,
                status_updated_by=actor,
            ),
        )
        return self._to_response(updated)

    def list_user_responsibility_flags(self) -> list[AssetResponsibilityFlagResponse]:
        grouped: dict[str, AssetResponsibilityFlagResponse] = {}

        for ticket in self.list_all():
            if not ticket.is_responsibility_flagged or not ticket.responsible_borrower_email:
                continue

            key = ticket.responsible_borrower_email.strip().lower()
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = AssetResponsibilityFlagResponse(
                    borrower_email=key,
                    borrower_name=ticket.responsible_borrower_name,
                    borrower_role=ticket.responsible_borrower_role,
                    active_damage_count=1 if ticket.status == "open" and ticket.ticket_type == "damage" else 0,
                    latest_ticket_title=ticket.title,
                    latest_asset_name=ticket.asset_name,
                    latest_reported_at=ticket.reported_at,
                    latest_ticket_id=ticket.id,
                )
                continue

            if ticket.status == "open" and ticket.ticket_type == "damage":
                existing.active_damage_count += 1
            if ticket.reported_at > existing.latest_reported_at:
                grouped[key] = existing.model_copy(
                    update={
                        "borrower_name": ticket.responsible_borrower_name or existing.borrower_name,
                        "borrower_role": ticket.responsible_borrower_role or existing.borrower_role,
                        "latest_ticket_title": ticket.title,
                        "latest_asset_name": ticket.asset_name,
                        "latest_reported_at": ticket.reported_at,
                        "latest_ticket_id": ticket.id,
                        "active_damage_count": existing.active_damage_count,
                    }
                )

        return sorted(grouped.values(), key=lambda item: item.latest_reported_at, reverse=True)
