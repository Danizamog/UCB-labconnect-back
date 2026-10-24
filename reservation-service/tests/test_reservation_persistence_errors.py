import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import reservations
from app.infrastructure.repositories.lab_reservation_repository import LabReservationRepository
from app.schemas.lab_reservation import LabReservationCreate


def _body() -> LabReservationCreate:
    return LabReservationCreate(
        laboratory_id="lab-1",
        area_id="area-1",
        requested_by="forged-user",
        purpose="Practica",
        start_at="2026-11-10T10:00:00",
        end_at="2026-11-10T11:00:00",
    )


def _prepare_create(monkeypatch, side_effect: Exception) -> None:
    monkeypatch.setattr(reservations, "user_penalty_repo", SimpleNamespace(get_active_for_user=lambda _user_id: None))
    monkeypatch.setattr(reservations, "ensure_user_can_reserve_laboratory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(reservations, "_validate_reservation_time_rules", lambda **_kwargs: None)
    monkeypatch.setattr(reservations, "lab_reservation_repo", SimpleNamespace(acreate=AsyncMock(side_effect=side_effect)))


def test_functional_persistence_error_remains_422(monkeypatch) -> None:
    _prepare_create(monkeypatch, ValueError("end_at debe ser mayor a start_at"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            reservations.create_reservation(
                _body(),
                {"user_id": "user-1", "role": "estudiante", "permissions": []},
            )
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "end_at debe ser mayor a start_at"


def test_infrastructure_persistence_error_returns_safe_503(monkeypatch) -> None:
    internal_message = "PocketBase http://internal:8090 rejected credential=super-secret"
    _prepare_create(monkeypatch, RuntimeError(internal_message))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            reservations.create_reservation(
                _body(),
                {"user_id": "user-1", "role": "estudiante", "permissions": []},
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "No se pudo guardar la reserva"
    assert internal_message not in str(exc.value.detail)
    assert "internal" not in str(exc.value.detail)
    assert "super-secret" not in str(exc.value.detail)


def test_pocketbase_error_is_converted_to_safe_infrastructure_error() -> None:
    internal_message = "PocketBase http://internal:8090 rejected credential=super-secret"
    repository = object.__new__(LabReservationRepository)
    repository._base = "/api/collections/reservations/records"
    repository._client = SimpleNamespace(request=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(internal_message)))

    with pytest.raises(RuntimeError) as exc:
        repository.create(_body(), current_user={"user_id": "user-1"})

    assert str(exc.value) == "No se pudo guardar la reserva"
    assert internal_message not in str(exc.value)
    assert "internal" not in str(exc.value)
    assert "super-secret" not in str(exc.value)
