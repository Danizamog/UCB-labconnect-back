from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


LoanType = Literal["asset", "material"]
LoanSourceType = Literal["manual", "practice_request"]
ReturnCondition = Literal["ok", "issues", "cancelled"]


class LoanCreate(BaseModel):
    loan_type: LoanType
    source_type: LoanSourceType = "manual"
    practice_request_id: int | None = None
    asset_id: int | None = None
    stock_item_id: int | None = None
    borrower_name: str = Field(min_length=2, max_length=120)
    borrower_email: str = Field(min_length=5, max_length=180)
    borrower_role: str = Field(default="Estudiante", min_length=2, max_length=80)
    purpose: str = Field(min_length=5, max_length=1200)
    quantity: int = Field(default=1, ge=1, le=500)
    due_at: datetime
    notes: str | None = Field(default=None, max_length=1500)
    affect_stock: bool = True


class LoanReturnPayload(BaseModel):
    return_notes: str | None = Field(default=None, max_length=1500)
    return_condition: ReturnCondition = "ok"
    incident_notes: str | None = Field(default=None, max_length=1500)


class LoanRecordOut(BaseModel):
    id: int
    loan_type: LoanType
    source_type: LoanSourceType
    practice_request_id: int | None = None
    asset_id: int | None = None
    stock_item_id: int | None = None
    laboratory_id: int | None = None
    item_name: str
    item_category: str | None = None
    borrower_name: str
    borrower_email: str
    borrower_role: str
    purpose: str
    quantity: int
    status: str
    raw_status: str
    return_condition: ReturnCondition | None = None
    notes: str | None = None
    return_notes: str | None = None
    incident_notes: str | None = None
    approved_by: str | None = None
    returned_by: str | None = None
    loaned_at: datetime
    due_at: datetime
    returned_at: datetime | None = None

    model_config = {"from_attributes": True}


class LoanBreakdownOut(BaseModel):
    label: str
    value: int


class LoanTrendPointOut(BaseModel):
    date: str
    value: int


class LoanStockAlertOut(BaseModel):
    id: int
    name: str
    category: str
    unit: str
    quantity_available: int
    minimum_stock: int

    model_config = {"from_attributes": True}


class LoanDashboardOut(BaseModel):
    total_active: int
    overdue_count: int
    due_today_count: int
    returned_this_month: int
    asset_loans_active: int
    material_loans_active: int
    low_stock_materials: int
    status_breakdown: list[LoanBreakdownOut]
    type_breakdown: list[LoanBreakdownOut]
    loan_trend: list[LoanTrendPointOut]
    recent_loans: list[LoanRecordOut]
    low_stock_alerts: list[LoanStockAlertOut]
