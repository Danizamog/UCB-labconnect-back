from pydantic import BaseModel, field_validator
from typing import Optional


class AssetCreate(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    location: str
    status: str = "available"
    item_type: str = "equipo"
    brand: Optional[str] = None
    model: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    expiry_date: Optional[str] = None
    provider: Optional[str] = None
    concentration: Optional[str] = None

    @field_validator('name', 'location')
    @classmethod
    def validate_required_fields(cls, v):
        if not v or not str(v).strip():
            raise ValueError('Este campo es obligatorio')
        return v.strip()


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    location: Optional[str] = None
    status: Optional[str] = None
    item_type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    expiry_date: Optional[str] = None
    provider: Optional[str] = None
    concentration: Optional[str] = None


class AssetStatusUpdate(BaseModel):
    status: str


class AssetOut(BaseModel):
    id: str
    name: str
    category: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    laboratory_id: Optional[int] = None
    location: Optional[str] = None
    status: str
    item_type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    expiry_date: Optional[str] = None
    provider: Optional[str] = None
    concentration: Optional[str] = None

    model_config = {"from_attributes": True}
