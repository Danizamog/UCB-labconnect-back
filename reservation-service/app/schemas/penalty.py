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
    asset_id: str = ""
    related_reservation_id: str = ""
    starts_at: str | None = None
    ends_at: str
    notes: str = ""


class PenaltyLiftRequest(BaseModel):
    lift_reason: str = ""


class PenaltyRegularizationStatus(BaseModel):
    is_regularized: bool = False
    has_open_damage_flags: bool = False
    active_damage_count: int = 0
    summary: str = ""
    latest_ticket_id: str = ""
    latest_ticket_title: str = ""
    latest_asset_name: str = ""
    latest_reported_at: str = ""


class PenaltyResponse(BaseModel):
    id: str
    user_id: str
    user_name: str
    user_email: str
    reason: str
    evidence_type: PenaltyEvidenceType
    evidence_report_id: str
    asset_id: str
    related_reservation_id: str
    starts_at: str
    ends_at: str
    notes: str
    status: str
    is_active: bool
    email_sent: bool = False
    created_at: str
    updated_at: str
    created_by: str
    created_by_name: str
    lifted_at: str = ""
    lifted_by: str = ""
    lifted_by_name: str = ""
    lift_reason: str = ""


class PenaltyLiftResponse(BaseModel):
    penalty: PenaltyResponse
    privileges_restored: bool = True


class PenaltyReactivationHistoryRecordCreate(BaseModel):
    penalty_id: str
    user_id: str
    user_name: str = ""
    user_email: str = ""
    actor_user_id: str
    actor_name: str
    executed_at: str
    lift_reason: str = ""
    resolution_notes: str = ""
    action_source: str = "admin_profile"
    user_was_inactive: bool = False
    user_is_active_after: bool = True
    privileges_restored: bool = True
    active_penalty_count_after: int = 0
    active_damage_count_at_validation: int = 0
    regularization_confirmed: bool = False
    regularization_summary: str = ""
    notification_sent: bool = True
    email_sent: bool = False


class PenaltyReactivationHistoryRecordResponse(PenaltyReactivationHistoryRecordCreate):
    id: str
    created: str = ""
    updated: str = ""


class PenaltyReactivationRequest(BaseModel):
    lift_reason: str = ""
    resolution_notes: str = ""
    action_source: str = "admin_profile"


class PenaltyReactivationContextResponse(BaseModel):
    user_id: str
    user_name: str = ""
    user_email: str = ""
    user_is_active: bool = True
    block_status: str = "active"
    active_penalty: PenaltyResponse | None = None
    active_penalty_count: int = 0
    can_reactivate: bool = False
    privileges_restored_if_confirmed: bool = False
    regularization: PenaltyRegularizationStatus = Field(default_factory=PenaltyRegularizationStatus)
    history: list[PenaltyReactivationHistoryRecordResponse] = Field(default_factory=list)


class PenaltyReactivationResponse(BaseModel):
    penalty: PenaltyResponse
    reactivation: PenaltyReactivationHistoryRecordResponse
    regularization: PenaltyRegularizationStatus
    privileges_restored: bool = True
    active_block_removed: bool = True
    user_status: str = "active"


class PenaltyListResponse(BaseModel):
    items: list[PenaltyResponse] = Field(default_factory=list)

