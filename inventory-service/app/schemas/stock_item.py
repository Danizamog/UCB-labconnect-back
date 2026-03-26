from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StockItemBase(BaseModel):
    name: str
    category: str
    unit: str
    quantity_available: int
    minimum_stock: int = 0
    laboratory_id: int | None = None
    description: str | None = None


class StockItemCreate(StockItemBase):
    pass


class StockItemUpdate(StockItemBase):
    pass


class StockQuantityUpdate(BaseModel):
    quantity_available: int


class StockMovementCreate(BaseModel):
    movement_type: Literal[
        "entry",
        "return",
        "consumption",
        "reservation_hold",
        "reservation_release",
    ]
    quantity: int = Field(ge=1, le=100000)
    reference_type: str | None = Field(default=None, max_length=40)
    reference_id: int | None = None
    notes: str | None = None


class StockMovementOut(BaseModel):
    id: int
    stock_item_id: int
    stock_item_name: str
    movement_type: str
    quantity_change: int
    quantity_before: int
    quantity_after: int
    reference_type: str | None = None
    reference_id: int | None = None
    performed_by: str
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StockItemOut(StockItemBase):
    id: int

    model_config = {"from_attributes": True}
