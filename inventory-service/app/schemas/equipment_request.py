from __future__ import annotations

from pydantic import BaseModel


class EquipmentRequestCreate(BaseModel):
    asset_id: str
    purpose: str = ""
    notes: str = ""
    requested_for: str = ""
    laboratory_id: str = ""
    lab_reservation_id: str = ""
    recurrence: str = ""
    recurrence_end_date: str = ""
    recurrence_group_id: str = ""
    # Datos del solicitante que el front puede enviar desde el perfil (docente).
    requested_by_name: str = ""
    requested_by_email: str = ""


class EquipmentRequestStatusUpdate(BaseModel):
    status: str
    notes: str | None = None


class EquipmentRequestResponse(BaseModel):
    id: str
    asset_id: str
    asset_name: str = ""
    asset_serial_number: str = ""
    laboratory_id: str = ""
    laboratory_name: str = ""
    requested_by: str = ""
    requested_by_name: str = ""
    requested_by_email: str = ""
    requested_by_role: str = ""
    purpose: str = ""
    notes: str = ""
    requested_for: str = ""
    status: str = "pending"
    lab_reservation_id: str = ""
    loan_record_id: str = ""
    recurrence: str = ""
    recurrence_end_date: str = ""
    recurrence_group_id: str = ""
    decided_by: str = ""
    decided_at: str = ""
    requested_at: str = ""
    created: str = ""
    updated: str = ""
