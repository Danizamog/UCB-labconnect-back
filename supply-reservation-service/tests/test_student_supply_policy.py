from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1.endpoints import supply_reservations
from app.schemas.supply_reservation import SupplyReservationCreate


@pytest.mark.parametrize("role", ["Invitado", "Docente", "Encargado de Laboratorio", "Administrador", "Administrador de Accesos", "OSI - Auditor de Seguridad", ""])
def test_personal_supply_requests_are_student_only(monkeypatch, role):
    probe = Mock(side_effect=AssertionError("Unauthorized requests must not read stock"))
    monkeypatch.setattr(supply_reservations, "stock_item_repo", SimpleNamespace(get_raw_by_id=probe))
    with pytest.raises(HTTPException) as error:
        supply_reservations.create_supply_reservation(SupplyReservationCreate(stock_item_id="stock", quantity=1), {"role": role, "permissions": []}, HTTPAuthorizationCredentials(scheme="Bearer", credentials="test"))
    assert error.value.status_code == 403
    probe.assert_not_called()
