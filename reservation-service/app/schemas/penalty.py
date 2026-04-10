from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PenaltyEvidenceType = Literal["damage_report", "maintenance_report"]


class PenaltyCreate(BaseModel):
    user_id: str
    user_name: str = ""
    user_email: str
    reason: str
    evidence_type: PenaltyEvidenceType = "damage_report"
    evidence_report_id: str = ""
    incident_scope: str = "laboratory"  # "asset" o "laboratory"
    incident_laboratory_id: str = ""
    incident_date: str = ""
    incident_start_time: str = ""
    incident_end_time: str = ""
    asset_id: str = ""
    related_reservation_id: str = ""
    starts_at: str | None = None
    ends_at: str
    notes: str = ""


class PenaltyLiftRequest(BaseModel):
    lift_reason: str = ""


class PenaltyResponse(BaseModel):
    id: str
    user_id: str
    user_name: str
    user_email: str
    reason: str
    evidence_type: PenaltyEvidenceType
    evidence_report_id: str
    incident_scope: str
    incident_laboratory_id: str
    incident_date: str
    incident_start_time: str
    incident_end_time: str
    asset_id: str
    related_reservation_id: str = ""
    starts_at: str
    ends_at: str
    notes: str
    status: str
    is_active: bool
    email_sent: bool = False
    created_at: str
    updated_at: str = ""
    created_by: str
    created_by_name: str
    lifted_at: str = ""
    lifted_by: str = ""
    lifted_by_name: str = ""
    lift_reason: str = ""


class PenaltyLiftResponse(BaseModel):
    penalty: PenaltyResponse
    privileges_restored: bool = True


class PenaltyListResponse(BaseModel):
    items: list[PenaltyResponse] = Field(default_factory=list)

