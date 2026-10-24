from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1.endpoints import supply_reservations
from app.schemas.supply_reservation import SupplyReservationCreate


def _response(status_code: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload if payload is not None else {},
        request=httpx.Request("GET", "http://reservation-service/resource"),
    )


@pytest.mark.parametrize(
    ("path", "owner_field", "payload"),
    [
        ("/v1/tutorial-sessions/tutorial-1", "tutor_id", {"id": "tutorial-1", "tutor_id": "user-1"}),
        ("/v1/reservations/reservation-1", "requested_by", {"id": "reservation-1", "requested_by": "user-1"}),
    ],
)
def test_owned_reference_is_allowed(monkeypatch, path, owner_field, payload) -> None:
    monkeypatch.setattr(supply_reservations.reservation_validation_client, "get", Mock(return_value=_response(200, payload)))

    result = supply_reservations._get_owned_reference(
        path,
        token="token",
        current_user={"user_id": "user-1"},
        owner_field=owner_field,
        resource_name="Recurso",
    )

    assert result["id"] == payload["id"]


def test_foreign_reference_is_denied(monkeypatch) -> None:
    monkeypatch.setattr(
        supply_reservations.reservation_validation_client,
        "get",
        Mock(return_value=_response(200, {"id": "tutorial-1", "tutor_id": "other-user"})),
    )

    with pytest.raises(HTTPException) as exc:
        supply_reservations._get_owned_reference(
            "/v1/tutorial-sessions/tutorial-1",
            token="token",
            current_user={"user_id": "user-1"},
            owner_field="tutor_id",
            resource_name="Tutoria",
        )

    assert exc.value.status_code == 403


def test_missing_reference_is_safe(monkeypatch) -> None:
    monkeypatch.setattr(supply_reservations.reservation_validation_client, "get", Mock(return_value=_response(404)))

    with pytest.raises(HTTPException) as exc:
        supply_reservations._get_owned_reference(
            "/v1/reservations/missing",
            token="token",
            current_user={"user_id": "user-1"},
            owner_field="requested_by",
            resource_name="Reserva",
        )

    assert exc.value.status_code == 404


@pytest.mark.parametrize("downstream_status", [401, 403])
def test_downstream_authorization_status_is_preserved(monkeypatch, downstream_status) -> None:
    monkeypatch.setattr(
        supply_reservations.reservation_validation_client,
        "get",
        Mock(return_value=_response(downstream_status, {"detail": "internal downstream detail"})),
    )

    with pytest.raises(HTTPException) as exc:
        supply_reservations._get_owned_reference(
            "/v1/reservations/reservation-1",
            token="secret-bearer-token",
            current_user={"user_id": "user-1"},
            owner_field="requested_by",
            resource_name="Reserva",
        )

    assert exc.value.status_code == downstream_status
    assert "internal downstream detail" not in str(exc.value.detail)
    assert "secret-bearer-token" not in str(exc.value.detail)


def test_downstream_timeout_fails_closed_without_sensitive_details(monkeypatch) -> None:
    monkeypatch.setattr(
        supply_reservations.reservation_validation_client,
        "get",
        Mock(side_effect=httpx.TimeoutException("timeout contacting http://reservation-service:8005?token=secret")),
    )

    with pytest.raises(HTTPException) as exc:
        supply_reservations._get_owned_reference(
            "/v1/reservations/reservation-1",
            token="secret-bearer-token",
            current_user={"user_id": "user-1"},
            owner_field="requested_by",
            resource_name="Reserva",
        )

    assert exc.value.status_code == 503
    assert "reservation-service" not in str(exc.value.detail)
    assert "secret" not in str(exc.value.detail)


@pytest.mark.parametrize("downstream_status", [500, 503])
def test_downstream_server_error_fails_closed(monkeypatch, downstream_status) -> None:
    monkeypatch.setattr(
        supply_reservations.reservation_validation_client,
        "get",
        Mock(return_value=_response(downstream_status, {"detail": "PocketBase http://internal:8090 failed"})),
    )

    with pytest.raises(HTTPException) as exc:
        supply_reservations._get_owned_reference(
            "/v1/reservations/reservation-1",
            token="secret-bearer-token",
            current_user={"user_id": "user-1"},
            owner_field="requested_by",
            resource_name="Reserva",
        )

    assert exc.value.status_code == 503
    assert "PocketBase" not in str(exc.value.detail)
    assert "internal" not in str(exc.value.detail)


def test_invalid_downstream_json_fails_closed(monkeypatch) -> None:
    response = httpx.Response(
        200,
        content=b"http://internal:8090 secret-token invalid-json",
        request=httpx.Request("GET", "http://reservation-service/resource"),
    )
    monkeypatch.setattr(supply_reservations.reservation_validation_client, "get", Mock(return_value=response))

    with pytest.raises(HTTPException) as exc:
        supply_reservations._get_owned_reference(
            "/v1/reservations/reservation-1",
            token="secret-bearer-token",
            current_user={"user_id": "user-1"},
            owner_field="requested_by",
            resource_name="Reserva",
        )

    assert exc.value.status_code == 503
    assert "internal" not in str(exc.value.detail)
    assert "secret" not in str(exc.value.detail)


def test_manipulated_reference_is_not_created(monkeypatch) -> None:
    stock_repo = SimpleNamespace(get_raw_by_id=lambda _item_id: {"quantity_available": 10})
    create = Mock()
    monkeypatch.setattr(supply_reservations, "stock_item_repo", stock_repo)
    monkeypatch.setattr(supply_reservations, "supply_reservation_repo", SimpleNamespace(create=create))
    monkeypatch.setattr(
        supply_reservations,
        "_get_owned_reference",
        Mock(side_effect=HTTPException(status_code=403, detail="No tienes acceso a la tutoria")),
    )

    with pytest.raises(HTTPException) as exc:
        supply_reservations.create_supply_reservation(
            SupplyReservationCreate(stock_item_id="stock-1", quantity=1, tutorial_session_id="foreign"),
            {"user_id": "user-1", "username": "user@ucb.edu.bo"},
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"),
        )

    assert exc.value.status_code == 403
    create.assert_not_called()


def test_detail_uses_stable_user_id_for_ownership(monkeypatch) -> None:
    record = SimpleNamespace(requested_by="user-1")
    monkeypatch.setattr(supply_reservations, "supply_reservation_repo", SimpleNamespace(get_by_id=lambda _id: record))

    result = supply_reservations.get_supply_reservation(
        "supply-1",
        {"user_id": "user-1", "username": "user@ucb.edu.bo", "permissions": []},
    )

    assert result is record
