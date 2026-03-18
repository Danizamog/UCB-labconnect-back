from pydantic import BaseModel
from typing import Optional


class StockItemCreate(BaseModel):
    name: str
    category: str
    unit: str
    quantity_available: int = 0
    minimum_stock: int = 0
    laboratory_id: Optional[int] = None
    description: Optional[str] = None


class StockItemUpdate(BaseModel):
    name: str
    category: str
    unit: str
    quantity_available: int = 0
    minimum_stock: int = 0
    laboratory_id: Optional[int] = None
    description: Optional[str] = None


class StockQuantityUpdate(BaseModel):
    quantity_available: int


class StockItemOut(BaseModel):
    id: int
    name: str
    category: str
    unit: str
    quantity_available: int
    minimum_stock: int
    laboratory_id: Optional[int] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}