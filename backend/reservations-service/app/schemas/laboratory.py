from pydantic import BaseModel
from typing import Optional


class LaboratoryCreate(BaseModel):
    name: str
    location: str
    capacity: int
    description: Optional[str] = None
    is_active: bool = True


class LaboratoryUpdate(BaseModel):
    name: str
    location: str
    capacity: int
    description: Optional[str] = None
    is_active: bool = True


class LaboratoryOut(BaseModel):
    id: int
    name: str
    location: str
    capacity: int
    description: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}