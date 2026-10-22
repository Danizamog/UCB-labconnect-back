import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-auth-integration")
os.environ["POCKETBASE_URL"] = ""

from fastapi.testclient import TestClient

from app.application.container import user_repository
from app.domain.entities.user import User
from app.infrastructure.security.password import hash_password
from app.application.use_cases.login_with_google import LoginWithGoogle
from app.main import app


def test_password_change_revokes_previous_token() -> None:
    email = "credential.flow@ucb.edu.bo"
    user_repository.save_with_password(
        User(id="credential-flow", username=email, name="Credential Flow", role="Estudiante"),
        "InitialPass2026!",
    )
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": email, "password": "InitialPass2026!"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    changed = client.post(
        "/v1/auth/change-password",
        headers=headers,
        json={
            "current_password": "InitialPass2026!",
            "new_password": "ChangedPass2026#",
            "new_password_confirm": "ChangedPass2026#",
        },
    )

    assert changed.status_code == 204
    assert client.get("/v1/users/me", headers=headers).status_code == 401
    assert client.post("/v1/auth/login", json={"username": email, "password": "ChangedPass2026#"}).status_code == 200


def test_google_account_cannot_use_local_password() -> None:
    email = "sso.only@ucb.edu.bo"
    user_repository.save_with_password(
        User(id="sso-only", username=email, name="SSO Only", role="Estudiante", auth_provider="google"),
        "UnknownRandom2026!",
    )
    response = TestClient(app).post(
        "/v1/auth/login",
        json={"username": email, "password": "UnknownRandom2026!"},
    )
    assert response.status_code == 401


def test_google_sso_keeps_existing_local_credentials() -> None:
    email = "dual.login@ucb.edu.bo"
    user_repository.save_with_password(
        User(id="dual-login", username=email, name="Dual Login", role="Estudiante"),
        "ExistingPass2026!",
    )

    class GoogleVerifier:
        def verify(self, _credential):
            return {
                "email": email,
                "name": "Dual Login",
                "picture": "",
                "google_sub": "google-dual-login",
            }

    LoginWithGoogle(user_repository, GoogleVerifier()).execute("valid-google-credential")

    user = user_repository.get_by_username(email)
    assert user is not None
    assert user.auth_provider == "local"
    assert user_repository.authenticate(email, "ExistingPass2026!") is not None


def test_account_locks_after_three_failed_attempts() -> None:
    email = "lock.after.three@ucb.edu.bo"
    user_repository.save_with_password(User(id="lock-three", username=email, name="Lock Three"), "ValidPass2026!")
    client = TestClient(app)
    for _ in range(3):
        assert client.post("/v1/auth/login", json={"username": email, "password": "WrongPass2026!"}).status_code == 401
    locked = user_repository.get_by_username(email)
    assert locked is not None
    assert locked.security_locked is True
    assert locked.failed_login_attempts == 3
    assert client.post("/v1/auth/login", json={"username": email, "password": "ValidPass2026!"}).status_code == 401


def test_password_history_rejects_recent_password() -> None:
    email = "password.history@ucb.edu.bo"
    user = user_repository.save_with_password(User(id="history-user", username=email, name="History User"), "InitialPass2026!")
    user_repository.record_password_hash(user.id or "", hash_password("InitialPass2026!"), "created")
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": email, "password": "InitialPass2026!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.post("/v1/auth/change-password", headers=headers, json={"current_password": "InitialPass2026!", "new_password": "SecondPass2026!", "new_password_confirm": "SecondPass2026!"}).status_code == 204
    login = client.post("/v1/auth/login", json={"username": email, "password": "SecondPass2026!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.post("/v1/auth/change-password", headers=headers, json={"current_password": "SecondPass2026!", "new_password": "InitialPass2026!", "new_password_confirm": "InitialPass2026!"})
    assert response.status_code == 409
