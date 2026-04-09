from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

MaintenanceTicketType = Literal["maintenance", "damage"]
MaintenanceTicketStatus = Literal["open", "closed"]
MaintenanceSeverity = Literal["low", "medium", "high", "critical"]


class AssetMaintenanceTicketCreate(BaseModel):
    ticket_type: MaintenanceTicketType
    title: str
    description: str
    severity: MaintenanceSeverity = "medium"
    evidence_report_id: str = ""


class AssetMaintenanceTicketClose(BaseModel):
    resolution_notes: str


class AssetMaintenanceTicketResponse(BaseModel):
    id: str
    asset_id: str
    asset_name: str
    ticket_type: MaintenanceTicketType
    title: str
    description: str
    severity: MaintenanceSeverity
    evidence_report_id: str
    status: MaintenanceTicketStatus
    reported_at: str
    reported_by: str
    resolved_at: str = ""
    resolved_by: str = ""
    resolution_notes: str = ""
    asset_status_before: str = ""
    asset_status_after_open: str = ""
    asset_status_after_close: str = ""
    related_loan_id: str = ""
    related_loan_status: str = ""
    related_loaned_at: str = ""
    responsible_borrower_name: str = ""
    responsible_borrower_email: str = ""
    responsible_borrower_role: str = ""
    is_responsibility_flagged: bool = False
    created: str = ""
    updated: str = ""


class AssetResponsibilityFlagResponse(BaseModel):
    borrower_email: str
    borrower_name: str = ""
    borrower_role: str = ""
    active_damage_count: int = 0
    latest_ticket_title: str = ""
    latest_asset_name: str = ""
    latest_reported_at: str = ""
    latest_ticket_id: str = ""
