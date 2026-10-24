import httpx
import pytest
from fastapi import HTTPException

from app.core import dependencies


def _response(status_code: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload if payload is not None else {},
        request=httpx.Request("GET", "http://auth-service/v1/auth/validate"),
    )


def test_revoked_session_is_not_authorized_from_cache(monkeypatch) -> None:
    responses = iter([
        _response(200, {"subject": "user@ucb.edu.bo", "user_id": "user-1", "role": "Estudiante", "permissions": []}),
        _response(401, {"detail": "Sesion revocada"}),
    ])
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return next(responses)

    dependencies._TOKEN_VALIDATION_CACHE.clear()
    monkeypatch.setattr(dependencies.settings, "token_cache_ttl_seconds", 0)
    monkeypatch.setattr(dependencies.auth_validation_client, "get", fake_get)

    first = dependencies._resolve_live_payload("token-before-revocation", {})
    assert first["user_id"] == "user-1"

    with pytest.raises(HTTPException) as exc:
        dependencies._resolve_live_payload("token-before-revocation", {})

    assert exc.value.status_code == 401
    assert len(calls) == 2

