from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.datetime_utils import is_valid_block_end, is_valid_block_start


class _LabScheduleBase(BaseModel):
    @field_validator("weekday", check_fields=False)
    @classmethod
    def _validate_weekday(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value < 0 or value > 6:
            raise ValueError("weekday debe estar entre 0 y 6")
        return value

    @field_validator("start_time", check_fields=False)
    @classmethod
    def _validate_start(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not is_valid_block_start(value):
            raise ValueError("start_time debe coincidir con el inicio de un bloque academico")
        return value

    @field_validator("end_time", check_fields=False)
    @classmethod
    def _validate_end(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not is_valid_block_end(value):
            raise ValueError("end_time debe coincidir con el fin de un bloque academico")
        return value


class LabScheduleCreate(_LabScheduleBase):
    laboratory_id: str
    weekday: int
    start_time: str
    end_time: str
    subject: str = Field(min_length=1)
    description: str | None = None
    is_active: bool | None = None
    teacher_id: str | None = None
    teacher_name: str | None = None
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    approval_reason: str = ""
    approved_by: str = ""
    approved_at: str = ""

    @model_validator(mode="after")
    def _validate_range(self) -> "LabScheduleCreate":
        if self.start_time >= self.end_time:
            raise ValueError("end_time debe ser mayor a start_time")
        return self


class LabScheduleUpdate(_LabScheduleBase):
    laboratory_id: str | None = None
    weekday: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    subject: str | None = None
    description: str | None = None
    is_active: bool | None = None
    teacher_id: str | None = None
    teacher_name: str | None = None
    approval_status: Literal["pending", "approved", "rejected"] | None = None
    approval_reason: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None

    @model_validator(mode="after")
    def _validate_range(self) -> "LabScheduleUpdate":
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValueError("end_time debe ser mayor a start_time")
        return self


class LabScheduleResponse(BaseModel):
    id: str
    laboratory_id: str
    weekday: int
    start_time: str = "08:00"
    end_time: str = "09:00"
    subject: str = ""
    description: str = ""
    is_active: bool = True
    teacher_id: str = ""
    teacher_name: str = ""
    approval_status: str = "approved"
    approval_reason: str = ""
    approved_by: str = ""
    approved_at: str = ""
    created: str = ""
    updated: str = ""

    open_time: str | None = None
    close_time: str | None = None
    slot_minutes: int | None = None

    @property
    def start(self) -> str:
        return self.start_time or self.open_time or "08:00"

    @property
    def end(self) -> str:
        return self.end_time or self.close_time or "09:00"


class LabScheduleApproval(BaseModel):
    status: Literal["approved", "rejected"]
    reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _require_rejection_reason(self) -> "LabScheduleApproval":
        self.reason = self.reason.strip()
        if self.status == "rejected" and not self.reason:
            raise ValueError("Debes indicar un motivo para rechazar la clase")
        return self
