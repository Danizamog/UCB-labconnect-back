from __future__ import annotations
from pydantic import BaseModel


class LaboratoryCreate(BaseModel):
    name: str
    location: str = ""
    capacity: int = 0
    description: str = ""
    is_active: bool = True
    area_id: str = ""


class LaboratoryUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    capacity: int | None = None
    description: str | None = None
    is_active: bool | None = None
    area_id: str | None = None


class LaboratoryResponse(BaseModel):
    id: str
    name: str
    location: str
    capacity: int
    description: str
    is_active: bool
    area_id: str
    area_name: str | None = None
    created: str
    updated: str
