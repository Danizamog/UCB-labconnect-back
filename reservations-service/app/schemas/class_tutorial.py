from datetime import date as date_type
from datetime import datetime as datetime_type
from datetime import time as time_type

from pydantic import BaseModel


class ClassTutorialCreate(BaseModel):
    laboratory_id: int
    session_type: str
    date: date_type
    start_time: time_type
    end_time: time_type
    title: str
    facilitator_name: str
    target_group: str | None = None
    academic_unit: str | None = None
    needs_support: bool = False
    support_topic: str | None = None
    notes: str | None = None


class ClassTutorialUpdate(BaseModel):
    laboratory_id: int | None = None
    session_type: str | None = None
    date: date_type | None = None
    start_time: time_type | None = None
    end_time: time_type | None = None
    title: str | None = None
    facilitator_name: str | None = None
    target_group: str | None = None
    academic_unit: str | None = None
    needs_support: bool | None = None
    support_topic: str | None = None
    notes: str | None = None


class ClassTutorialOut(BaseModel):
    id: int
    laboratory_id: int
    laboratory_name: str
    session_type: str
    date: date_type
    start_time: time_type
    end_time: time_type
    title: str
    facilitator_name: str
    target_group: str | None = None
    academic_unit: str | None = None
    needs_support: bool
    support_topic: str | None = None
    notes: str | None = None
    created_at: datetime_type
    updated_at: datetime_type
