from __future__ import annotations

from pydantic import BaseModel

BLOCK_TYPES = {"maintenance", "event", "holiday", "other"}


class LabBlockCreate(BaseModel):
    laboratory_id: str
    start_at: str
    end_at: str
    reason: str = ""
    block_type: str
    created_by: str | None = None
    is_active: bool | None = None


class LabBlockUpdate(BaseModel):
    laboratory_id: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    reason: str | None = None
    block_type: str | None = None
    created_by: str | None = None
    is_active: bool | None = None


class LabBlockResponse(BaseModel):
    id: str
    laboratory_id: str
    start_at: str
    end_at: str
    reason: str
    block_type: str
    created_by: str
    is_active: bool
    created: str
    updated: str
