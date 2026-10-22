import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-password-reset")
os.environ["POCKETBASE_URL"] = ""

from fastapi.testclient import TestClient

from app.application.use_cases.login_user import LoginUser
from app.domain.entities.user import User
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository
from app.infrastructure.cache import TTLCache
from app.interfaces.http import router
from app.main import app


def test_password_reset_enables_credentials_for_google_account(monkeypatch):
    repository = InMemoryUserRepository()
    user = repository.save_with_password(
        User(
            id="google-account",
            username="person.test@ucb.edu.bo",
            name="Person Test",
            auth_provider="google",
        ),
        "ExistingPass2026!",
    )
    monkeypatch.setattr(router, "user_repository", repository)
    monkeypatch.setattr(router, "login_user_use_case", LoginUser(repository))
    monkeypatch.setattr(router, "session_cache", TTLCache(30))
    monkeypatch.setattr(router.settings, "smtp_host", "mailpit")
    monkeypatch.setattr(router.settings, "smtp_sender", "labconnect@ucb.edu.bo")
    sent = {}

    def capture_reset_email(*, recipient, name, token):
        sent.update({"recipient": recipient, "name": name, "token": token})
        return True

    monkeypatch.setattr(router, "send_password_reset_email", capture_reset_email)
    client = TestClient(app)

    requested = client.post(
        "/v1/auth/password/forgot",
        json={"email": user.username},
    )
    assert requested.status_code == 200
    assert requested.json()["message"].startswith("Si la cuenta existe")
    assert sent["recipient"] == user.username

    reset = client.post(
        "/v1/auth/password/reset",
        json={
            "token": sent["token"],
            "new_password": "NewSecurePass2026!",
            "new_password_confirm": "NewSecurePass2026!",
        },
    )
    assert reset.status_code == 200
    assert repository.get_by_username(user.username).auth_provider == "local"
    assert client.post(
        "/v1/auth/login",
        json={"username": user.username, "password": "NewSecurePass2026!"},
    ).status_code == 200

    replay = client.post(
        "/v1/auth/password/reset",
        json={
            "token": sent["token"],
            "new_password": "AnotherSecurePass2026!",
            "new_password_confirm": "AnotherSecurePass2026!",
        },
    )
    assert replay.status_code == 400


def test_password_reset_rejects_weak_password(monkeypatch):
    repository = InMemoryUserRepository()
    repository.save_with_password(
        User(id="reset-user", username="reset.user@ucb.edu.bo", name="Reset User"),
        "ExistingPass2026!",
    )
    monkeypatch.setattr(router, "user_repository", repository)
    monkeypatch.setattr(router.settings, "smtp_host", "mailpit")
    monkeypatch.setattr(router.settings, "smtp_sender", "labconnect@ucb.edu.bo")
    sent = {}
    monkeypatch.setattr(
        router,
        "send_password_reset_email",
        lambda **kwargs: sent.update(kwargs) or True,
    )
    client = TestClient(app)
    client.post("/v1/auth/password/forgot", json={"email": "reset.user@ucb.edu.bo"})

    response = client.post(
        "/v1/auth/password/reset",
        json={
            "token": sent["token"],
            "new_password": "weak",
            "new_password_confirm": "weak",
        },
    )
    assert response.status_code == 422
