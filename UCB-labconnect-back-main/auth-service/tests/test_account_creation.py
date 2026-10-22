import os
import re

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-account-creation")
os.environ["POCKETBASE_URL"] = ""

import pytest
from fastapi.testclient import TestClient

from app.application.use_cases.login_user import LoginUser
from app.core.identity import build_institutional_email_candidates
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
    repo.save_with_password(User(username="access.test@ucb.edu.bo", role="Administrador de Accesos", permissions=["crear_usuarios", "consultar_usuarios", "dar_baja_usuarios"]), "AccessTest2026!")
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "access.test@ucb.edu.bo", "password": "AccessTest2026!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return client, repo, headers


def test_generated_credential_forces_first_change_and_is_not_exposed_later(accounts):
    client, repo, headers = accounts
    response = client.post("/v1/users/", headers=headers, json={"name": "Nuevo Docente Ejemplo", "profile_type": "teacher", "first_name": "Nuevo", "paternal_surname": "Docente", "maternal_surname": "Ejemplo"})
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
    first_payload = {"name": "Persona Uno Test", "profile_type": "student", "first_name": "Persona", "paternal_surname": "Uno", "maternal_surname": "Test"}
    second_payload = {"name": "Persona Dos Test", "profile_type": "student", "first_name": "Persona", "paternal_surname": "Dos", "maternal_surname": "Test"}
    first = client.post("/v1/users/", headers=headers, json=first_payload).json()
    second = client.post("/v1/users/", headers=headers, json=second_payload).json()
    assert first["temporary_password"] != second["temporary_password"]
    assert client.post("/v1/users/", json={"username": "three@ucb.edu.bo", "name": "Persona Tres"}).status_code == 401


def test_role_email_candidates_follow_student_and_teacher_conventions():
    assert build_institutional_email_candidates("student", "María José", "López", "Vargas", "@ucb.edu.bo") == [
        "maria.lopez@ucb.edu.bo",
        "maria.lopez.v@ucb.edu.bo",
    ]
    assert build_institutional_email_candidates("teacher", "Álvaro", "Pérez", "Soto", "@ucb.edu.bo") == [
        "a.perez.s@ucb.edu.bo",
        "a.perez@ucb.edu.bo",
    ]


def test_generated_identity_email_uses_collision_fallback_and_immutable_code(accounts):
    client, repo, headers = accounts
    payload = {
        "name": "Ana López Vargas", "profile_type": "student", "first_name": "Ana",
        "paternal_surname": "López", "maternal_surname": "Vargas",
    }
    first = client.post("/v1/users/", headers=headers, json=payload)
    second = client.post("/v1/users/", headers=headers, json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["username"] == "ana.lopez@ucb.edu.bo"
    assert second.json()["username"] == "ana.lopez.v@ucb.edu.bo"
    for response in (first, second):
        assert re.fullmatch(r"UCB-\d{4}-[A-F0-9]{8}", response.json()["user_code"])
    stored = repo.get_by_id(first.json()["id"])
    original_code = stored.user_code
    stored.name = "Nombre corregido"
    stored.user_code = "UCB-2099-DEADBEEF"
    repo.save(stored)
    assert repo.get_by_id(first.json()["id"]).user_code == original_code


def test_teacher_email_uses_fallback_then_conflicts_when_both_taken(accounts):
    client, _, headers = accounts
    payload = {
        "name": "Luis García Rojas", "profile_type": "teacher", "first_name": "Luis",
        "paternal_surname": "García", "maternal_surname": "Rojas",
    }
    first = client.post("/v1/users/", headers=headers, json=payload)
    second = client.post("/v1/users/", headers=headers, json=payload)
    third = client.post("/v1/users/", headers=headers, json=payload)
    assert first.json()["username"] == "l.garcia.r@ucb.edu.bo"
    assert second.json()["username"] == "l.garcia@ucb.edu.bo"
    assert third.status_code == 409


def test_deactivation_revokes_existing_jwt_on_next_request(accounts):
    client, repo, headers = accounts
    repo.save_with_password(User(username="inactive.target@ucb.edu.bo", role="Estudiante"), "TargetPass2026!")
    login = client.post("/v1/auth/login", json={"username": "inactive.target@ucb.edu.bo", "password": "TargetPass2026!"})
    target_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/v1/users/me", headers=target_headers).status_code == 200

    target = repo.get_by_username("inactive.target@ucb.edu.bo")
    assert client.delete(f"/v1/users/{target.id}", headers=headers).status_code == 204
    assert client.get("/v1/users/me", headers=target_headers).status_code == 401
    assert repo.get_by_id(target.id).is_active is False
