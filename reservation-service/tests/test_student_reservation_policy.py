import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import reservations
from app.schemas.lab_reservation import LabReservationCreate


@pytest.mark.parametrize("role", ["Invitado", "Docente", "Encargado de Laboratorio", "Administrador", "Administrador de Accesos", "OSI - Auditor de Seguridad", ""])
def test_only_students_can_create_personal_reservations(monkeypatch, role):
    probe = Mock(side_effect=AssertionError("Unauthorized requests must not reach persistence"))
    monkeypatch.setattr(reservations, "user_penalty_repo", SimpleNamespace(get_active_for_user=probe))
    body = LabReservationCreate(laboratory_id="lab", start_at="2026-11-10T10:00:00", end_at="2026-11-10T11:00:00")
    with pytest.raises(HTTPException) as error:
        asyncio.run(reservations.create_reservation(body, {"role": role, "user_id": "user", "permissions": ["gestionar_reservas"]}))
    assert error.value.status_code == 403
    probe.assert_not_called()


def test_guest_cannot_modify_an_existing_personal_reservation():
    with pytest.raises(HTTPException) as error:
        reservations._ensure_user_can_change_reservation(SimpleNamespace(), current_user={"role": "Invitado", "permissions": []}, operation="modify")
    assert error.value.status_code == 403
