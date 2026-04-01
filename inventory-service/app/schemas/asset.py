from __future__ import annotations
from pydantic import BaseModel

ASSET_STATUSES = {"available", "loaned", "maintenance", "damaged"}


class AssetCreate(BaseModel):
    name: str
    category: str = ""
    location: str = ""
    description: str = ""
    serial_number: str = ""
    laboratory_id: str = ""
    status: str = "available"
    status_updated_at: str = ""
    status_updated_by: str = ""


class AssetUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    location: str | None = None
    description: str | None = None
    serial_number: str | None = None
    laboratory_id: str | None = None
    status: str | None = None
    status_updated_at: str | None = None
    status_updated_by: str | None = None


class AssetResponse(BaseModel):
    id: str
    name: str
    category: str
    location: str
    description: str
    serial_number: str
    laboratory_id: str
    laboratory_name: str | None = None
    status: str
    status_updated_at: str
    status_updated_by: str
    created: str
    updated: str
