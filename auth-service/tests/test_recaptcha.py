import os
from unittest.mock import Mock
from urllib.parse import parse_qs

os.environ.setdefault("SECRET_KEY", "test-only-recaptcha-secret-for-jwt")
os.environ["POCKETBASE_URL"] = ""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.infrastructure.security import recaptcha
from app.interfaces.http import router
from app.main import app

HTTP_CLIENT = httpx.Client
LOGIN = {"username": "demo@ucb.edu.bo", "password": "NotASavedPassword2026!", "captcha_token": "captcha-test-token"}


@pytest.fixture
def protected_login(monkeypatch):
    monkeypatch.setattr(settings, "recaptcha_enabled", True)
    monkeypatch.setattr(settings, "recaptcha_site_key", "test-public-site-key")
    monkeypatch.setattr(settings, "recaptcha_secret_key", "test-server-secret")
    monkeypatch.setattr(settings, "recaptcha_allowed_hostnames", ("ucb-labconnect-front.pages.dev", "localhost", "127.0.0.1"))
    auth = Mock()
    auth.execute.return_value = "verified-login-token"
    audit = Mock()
    monkeypatch.setattr(router, "login_user_use_case", auth)
    monkeypatch.setattr(router, "_record_session", Mock())
    monkeypatch.setattr(router, "_audit", audit)
    return TestClient(app), auth, audit


def google_response(monkeypatch, result=None, *, code=200, fail=False, invalid_json=False):
    requests = []

    def respond(request):
        requests.append(request)
        if fail:
            raise httpx.ConnectTimeout("simulated outage")
        if invalid_json:
            return httpx.Response(200, text="invalid JSON")
        return httpx.Response(code, json=result)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(recaptcha.httpx, "Client", lambda **kwargs: HTTP_CLIENT(transport=transport, **kwargs))
    return requests


@pytest.mark.parametrize("hostname", ["ucb-labconnect-front.pages.dev", "localhost", "127.0.0.1"])
def test_verified_captcha_allows_password_login(protected_login, monkeypatch, hostname):
    client, auth, _ = protected_login
    sent = google_response(monkeypatch, {"success": True, "hostname": hostname})
    result = client.post("/v1/auth/login", json=LOGIN)
    assert result.status_code == 200
    auth.execute.assert_called_once_with(LOGIN["username"], LOGIN["password"])
    assert str(sent[0].url) == recaptcha.VERIFY_URL
    assert parse_qs(sent[0].content.decode()) == {"secret": ["test-server-secret"], "response": [LOGIN["captcha_token"]]}


@pytest.mark.parametrize("token", [None, "", "   "])
def test_missing_captcha_never_checks_password(protected_login, monkeypatch, token):
    client, auth, audit = protected_login
    sent = google_response(monkeypatch, {"success": True, "hostname": "localhost"})
    assert client.post("/v1/auth/login", json={**LOGIN, "captcha_token": token}).status_code == 403
    auth.execute.assert_not_called()
    assert sent == []
    assert LOGIN["password"] not in str(audit.call_args_list)


@pytest.mark.parametrize("result", [
    {"success": False, "error-codes": ["invalid-input-response"]},
    {"success": False, "error-codes": ["timeout-or-duplicate"]},
    {"success": True, "hostname": "evil.example"},
    {"success": True, "hostname": "ucb-labconnect-front.pages.dev.evil.example"},
    {"success": True},
    {"success": "true", "hostname": "localhost"},
])
def test_invalid_expired_reused_or_wrong_origin_is_rejected(protected_login, monkeypatch, result):
    client, auth, audit = protected_login
    google_response(monkeypatch, result)
    response = client.post("/v1/auth/login", json=LOGIN)
    assert response.status_code == 403
    auth.execute.assert_not_called()
    assert LOGIN["captcha_token"] not in response.text
    assert LOGIN["captcha_token"] not in str(audit.call_args_list)


@pytest.mark.parametrize("options", [{"fail": True}, {"code": 503}, {"invalid_json": True}, {"result": []}, {"result": {"success": False, "error-codes": ["invalid-input-secret"]}}])
def test_google_outage_or_invalid_configuration_fails_closed(protected_login, monkeypatch, options):
    client, auth, _ = protected_login
    google_response(monkeypatch, **options)
    assert client.post("/v1/auth/login", json=LOGIN).status_code == 503
    auth.execute.assert_not_called()


@pytest.mark.parametrize("field,value", [("recaptcha_secret_key", ""), ("recaptcha_site_key", ""), ("recaptcha_allowed_hostnames", ())])
def test_enabled_without_configuration_blocks_login(protected_login, monkeypatch, field, value):
    client, auth, _ = protected_login
    monkeypatch.setattr(settings, field, value)
    sent = google_response(monkeypatch, {"success": True, "hostname": "localhost"})
    assert client.post("/v1/auth/login", json=LOGIN).status_code == 503
    auth.execute.assert_not_called()
    assert sent == []
    config = client.get("/v1/auth/captcha/config").json()
    assert config == {"enabled": True, "configured": False, "site_key": None}


def test_public_configuration_never_exposes_secret(protected_login):
    client, _, _ = protected_login
    response = client.get("/v1/auth/captcha/config")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"enabled": True, "configured": True, "site_key": "test-public-site-key"}
    assert "test-server-secret" not in response.text


def test_explicitly_disabled_does_not_require_token(protected_login, monkeypatch):
    client, auth, _ = protected_login
    monkeypatch.setattr(settings, "recaptcha_enabled", False)
    assert client.post("/v1/auth/login", json={**LOGIN, "captcha_token": None}).status_code == 200
    auth.execute.assert_called_once()


def test_rejected_credentials_still_require_new_captcha(protected_login, monkeypatch):
    client, auth, _ = protected_login
    google_response(monkeypatch, {"success": True, "hostname": "localhost"})
    auth.execute.side_effect = ValueError("Cuenta no reconocida")
    assert client.post("/v1/auth/login", json=LOGIN).status_code == 401
    auth.execute.reset_mock()
    google_response(monkeypatch, {"success": False, "error-codes": ["timeout-or-duplicate"]})
    assert client.post("/v1/auth/login", json=LOGIN).status_code == 403
    auth.execute.assert_not_called()
