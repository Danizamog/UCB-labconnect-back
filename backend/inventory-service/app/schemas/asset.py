from pydantic import BaseModel
from typing import Optional


class AssetCreate(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    quantity_total: int = 1
    quantity_available: int = 1
    status: str = "available"


class AssetUpdate(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    quantity_total: int = 1
    quantity_available: int = 1
    status: str = "available"


class AssetStatusUpdate(BaseModel):
    status: str


class AssetOut(BaseModel):
    id: int
    name: str
    category: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    quantity_total: int
    quantity_available: int
    status: str

    model_config = {"from_attributes": True}
