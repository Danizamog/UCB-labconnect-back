import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-account-creation")
os.environ["POCKETBASE_URL"] = ""

import pytest
from fastapi.testclient import TestClient

from app.application.use_cases.login_user import LoginUser
from app.domain.entities.user import User
from app.domain.password_policy import validate_password
from app.infrastructure.cache import TTLCache
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository
from app.interfaces.http import router
from app.main import app


@pytest.fixture
def accounts(monkeypatch):
    repo = InMemoryUserRepository()
    monkeypatch.setattr(router, "user_repository", repo)
    monkeypatch.setattr(router, "login_user_use_case", LoginUser(repo))
    monkeypatch.setattr(router, "session_cache", TTLCache(30))
    repo.save_with_password(User(username="access.test@ucb.edu.bo", role="Administrador de Accesos", permissions=["crear_usuarios", "consultar_usuarios"]), "AccessTest2026!")
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "access.test@ucb.edu.bo", "password": "AccessTest2026!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return client, repo, headers


def test_generated_credential_forces_first_change_and_is_not_exposed_later(accounts):
    client, repo, headers = accounts
    response = client.post("/v1/users/", headers=headers, json={"username": "new.teacher@ucb.edu.bo", "name": "Nuevo Docente", "profile_type": "teacher"})
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    temporary = data["temporary_password"]
    assert len(temporary) == 20
    validate_password(temporary)
    assert data["must_change_password"] is True
    assert data["user_code"].startswith("UCB-")
    assert data["auth_provider"] == "local"
    assert "temporary_password" not in client.get(f"/v1/users/{data['id']}", headers=headers).json()
    assert temporary not in str(repo.list_security_records("security_audit_event"))
    login = client.post("/v1/auth/login", json={"username": data["username"], "password": temporary})
    assert login.status_code == 200
    own_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/v1/users/me", headers=own_headers).json()["must_change_password"] is True
    assert client.get("/v1/users/", headers=own_headers).status_code == 403
    changed = client.post("/v1/auth/change-password", headers=own_headers, json={"current_password": temporary, "new_password": "DefinitivePass2026!", "new_password_confirm": "DefinitivePass2026!"})
    assert changed.status_code == 204
    assert client.get("/v1/users/me", headers=own_headers).status_code == 401
    fresh = client.post("/v1/auth/login", json={"username": data["username"], "password": "DefinitivePass2026!"})
    fresh_headers = {"Authorization": f"Bearer {fresh.json()['access_token']}"}
    assert client.get("/v1/users/me", headers=fresh_headers).json()["must_change_password"] is False


@pytest.mark.parametrize("email", ["someone@gmail.com", "someone@ucb.edu.bo.evil.com", "a@@ucb.edu.bo", "a b@ucb.edu.bo", "@ucb.edu.bo"])
def test_account_creation_rejects_invalid_domain(accounts, email):
    client, _, headers = accounts
    assert client.post("/v1/users/", headers=headers, json={"username": email, "name": "Persona"}).status_code == 400


def test_password_generator_is_random_and_creation_is_authorized(accounts):
    client, _, headers = accounts
    first = client.post("/v1/users/", headers=headers, json={"username": "one@ucb.edu.bo", "name": "Persona Uno"}).json()
    second = client.post("/v1/users/", headers=headers, json={"username": "two@ucb.edu.bo", "name": "Persona Dos"}).json()
    assert first["temporary_password"] != second["temporary_password"]
    assert client.post("/v1/users/", json={"username": "three@ucb.edu.bo", "name": "Persona Tres"}).status_code == 401
