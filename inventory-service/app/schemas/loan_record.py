from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

LoanStatus = Literal["active", "returned"]
LoanReturnCondition = Literal["ok", "damaged"]


class LoanRecordCreate(BaseModel):
    asset_id: str
    borrower_id: str
    borrower_name: str
    borrower_email: str = ""
    borrower_role: str = ""
    purpose: str = ""
    notes: str = ""
    due_at: str = ""


class LoanRecordReturn(BaseModel):
    return_condition: LoanReturnCondition = "ok"
    return_notes: str = ""
    incident_notes: str = ""


class LoanRecordResponse(BaseModel):
    id: str
    asset_id: str
    asset_name: str
    asset_serial_number: str = ""
    laboratory_id: str = ""
    laboratory_name: str = ""
    borrower_id: str
    borrower_name: str
    borrower_email: str = ""
    borrower_role: str = ""
    purpose: str = ""
    notes: str = ""
    status: LoanStatus = "active"
    loaned_by: str = ""
    returned_by: str = ""
    loaned_at: str
    due_at: str = ""
    returned_at: str = ""
    return_condition: LoanReturnCondition | str = "ok"
    return_notes: str = ""
    incident_notes: str = ""
    created: str = ""
    updated: str = ""


class LoanDashboardResponse(BaseModel):
    total_records: int
    active_count: int
    returned_count: int
    damaged_returns_count: int
    active_loans: list[LoanRecordResponse]
