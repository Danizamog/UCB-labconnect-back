from __future__ import annotations
from pydantic import BaseModel


class StockItemCreate(BaseModel):
    name: str
    category: str = ""
    unit: str = ""
    quantity_available: int = 0
    minimum_stock: int = 0
    laboratory_id: str = ""
    description: str = ""


class StockItemUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    unit: str | None = None
    quantity_available: int | None = None
    minimum_stock: int | None = None
    laboratory_id: str | None = None
    description: str | None = None


class StockItemResponse(BaseModel):
    id: str
    name: str
    category: str
    unit: str
    quantity_available: int
    minimum_stock: int
    laboratory_id: str
    laboratory_name: str | None = None
    description: str
    created: str
    updated: str
