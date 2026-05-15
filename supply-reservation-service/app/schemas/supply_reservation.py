from pydantic import BaseModel, Field


class SupplyReservationCreate(BaseModel):
    stock_item_id: str
    quantity: int = Field(gt=0)
    requested_for: str = ""
    notes: str = ""
    laboratory_id: str = ""
    tutorial_session_id: str = ""
    lab_reservation_id: str = ""


class SupplyReservationStatusUpdate(BaseModel):
    status: str
    notes: str | None = None


class SupplyReservationResponse(BaseModel):
    id: str
    stock_item_id: str
    stock_item_name: str | None = None
    laboratory_id: str = ""
    laboratory_name: str | None = None
    quantity: int
    quantity_available: int = 0
    status: str
    requested_by: str
    requested_for: str
    notes: str
    tutorial_session_id: str = ""
    lab_reservation_id: str = ""
    created: str
    updated: str
