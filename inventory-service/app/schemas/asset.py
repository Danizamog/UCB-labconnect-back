from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class AssetCreate(BaseModel):
    name: str
    category: str
    location: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    status: str = "available"


class AssetUpdate(BaseModel):
    name: str
    category: str
    location: str
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
    location: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    status: str
    status_updated_at: datetime | None = None
    status_updated_by: str | None = None

    model_config = {"from_attributes": True}


class AssetStatusLogOut(BaseModel):
    id: int
    asset_id: int
    previous_status: str | None = None
    next_status: str
    changed_by: str
    changed_at: datetime
    notes: str | None = None
