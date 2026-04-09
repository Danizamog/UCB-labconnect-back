from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MaintenanceTicketType = Literal["maintenance", "damage"]
MaintenanceTicketStatus = Literal["open", "closed"]
MaintenanceSeverity = Literal["low", "medium", "high", "critical"]


class AssetMaintenanceTicketCreate(BaseModel):
    ticket_type: MaintenanceTicketType
    title: str = Field(min_length=5, max_length=160)
    description: str = Field(min_length=10, max_length=4000)
    severity: MaintenanceSeverity = "medium"
    evidence_report_id: str = Field(default="", max_length=120)


class AssetMaintenanceTicketClose(BaseModel):
    resolution_notes: str = Field(min_length=5, max_length=4000)


class AssetMaintenanceTicketResponse(BaseModel):
    id: str
    asset_ref: str = ""
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
    reported_by_user_id: str = ""
    reported_by_email: str = ""
    resolved_at: str = ""
    resolved_by: str = ""
    resolved_by_user_id: str = ""
    resolved_by_email: str = ""
    resolution_notes: str = ""
    asset_status_before: str = ""
    asset_status_after_open: str = ""
    related_loan_id: str = ""
    responsible_borrower_name: str = ""
    responsible_borrower_email: str = ""
    is_responsibility_flagged: bool = False
    created: str = ""
    updated: str = ""


class AssetResponsibilityFlagResponse(BaseModel):
    borrower_email: str
    borrower_name: str = ""
    active_damage_count: int = 0
    latest_ticket_title: str = ""
    latest_asset_name: str = ""
    latest_reported_at: str = ""
    latest_ticket_id: str = ""
