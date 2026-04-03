from pydantic import BaseModel, Field


class SupplyReservationCreate(BaseModel):
    stock_item_id: str
    quantity: int = Field(gt=0)
    requested_for: str = ""
    notes: str = ""


class SupplyReservationStatusUpdate(BaseModel):
    status: str
    notes: str | None = None


class SupplyReservationResponse(BaseModel):
    id: str
    stock_item_id: str
    stock_item_name: str | None = None
    quantity: int
    status: str
    requested_by: str
    requested_for: str
    notes: str
    created: str
    updated: str
