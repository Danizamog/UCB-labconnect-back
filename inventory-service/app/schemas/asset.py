from pydantic import BaseModel
from typing import Optional


class AssetCreate(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    status: str = "available"


class AssetUpdate(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    status: str = "available"


class AssetStatusUpdate(BaseModel):
    status: str


class AssetOut(BaseModel):
    id: str
    name: str
    category: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    status: str

    model_config = {"from_attributes": True}
