from datetime import date as date_type
from datetime import datetime as datetime_type
from datetime import time as time_type

from pydantic import BaseModel


class PracticeMaterialCreate(BaseModel):
    asset_id: int
    quantity: int
    material_name: str | None = None


class PracticeRequestCreate(BaseModel):
    subject_name: str
    laboratory_id: int
    date: date_type
    start_time: time_type
    end_time: time_type
    materials: list[PracticeMaterialCreate] = []
    needs_support: bool = False
    support_topic: str | None = None
    notes: str


class PracticeMaterialResponse(BaseModel):
    id: int
    asset_id: int
    material_name: str
    quantity: int


class PracticeMaterialTrackingResponse(BaseModel):
    loan_id: int
    material_name: str
    quantity: int
    status: str
    return_condition: str | None = None
    return_notes: str | None = None
    incident_notes: str | None = None
    due_at: datetime_type | None = None


class PracticeRequestResponse(BaseModel):
    id: int
    user_id: str
    username: str
    subject_name: str | None = None
    laboratory_id: int
    laboratory_name: str
    date: date_type
    start_time: time_type
    end_time: time_type
    needs_support: bool
    support_topic: str | None = None
    notes: str
    review_comment: str | None = None
    status: str
    created_at: datetime_type
    status_updated_at: datetime_type
    user_notification_read: bool
    material_tracking_status: str | None = None
    materials: list[PracticeMaterialResponse]
    material_loans: list[PracticeMaterialTrackingResponse] = []


class ReservationNotification(BaseModel):
    id: int
    title: str
    message: str
    status: str
    review_comment: str | None = None
    created_at: datetime_type
    read: bool
    laboratory_name: str
    date: date_type
    start_time: time_type
    end_time: time_type
