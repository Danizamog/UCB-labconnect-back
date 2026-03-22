from datetime import datetime

from pydantic import BaseModel


class AssetLoanCreate(BaseModel):
    asset_id: int
    borrower_name: str
    borrower_email: str
    quantity: int = 1
    notes: str | None = None
    due_at: datetime | None = None


class AssetLoanOut(BaseModel):
    id: int
    asset_id: int
    borrower_name: str
    borrower_email: str
    quantity: int
    notes: str | None = None
    created_at: datetime
    due_at: datetime | None = None
    returned_at: datetime | None = None
    status: str

    model_config = {"from_attributes": True}
