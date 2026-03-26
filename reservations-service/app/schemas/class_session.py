from datetime import date as date_type
from datetime import datetime as datetime_type
from datetime import time as time_type

from pydantic import BaseModel


class ClassSessionCreate(BaseModel):
    laboratory_id: int
    date: date_type
    start_time: time_type
    end_time: time_type
    subject_name: str
    teacher_name: str
    needs_support: bool = False
    support_topic: str | None = None
    notes: str | None = None


class ClassSessionUpdate(BaseModel):
    laboratory_id: int | None = None
    date: date_type | None = None
    start_time: time_type | None = None
    end_time: time_type | None = None
    subject_name: str | None = None
    teacher_name: str | None = None
    needs_support: bool | None = None
    support_topic: str | None = None
    notes: str | None = None


class ClassSessionOut(BaseModel):
    id: int
    laboratory_id: int
    laboratory_name: str
    date: date_type
    start_time: time_type
    end_time: time_type
    subject_name: str
    teacher_name: str
    needs_support: bool
    support_topic: str | None = None
    notes: str | None = None
    created_at: datetime_type
