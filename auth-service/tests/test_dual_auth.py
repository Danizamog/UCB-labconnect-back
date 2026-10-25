from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.application.use_cases.login_user import LoginUser
from app.application.use_cases.login_with_google import LoginWithGoogle
from app.domain.account_security import AccountLockedError
from app.domain.entities.user import User
from app.infrastructure.cache import TTLCache
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository
from app.infrastructure.security.token_provider import create_access_token, decode_token
from app.interfaces.http import router
from app.main import app

PASSWORD = "SecureInitial2026!"
NEXT_PASSWORD = "ChangedSecure2026#"
IDENTITY = {"email": "student@ucb.edu.bo", "name": "Estudiante", "google_sub": "google-sub-student", "picture": None}


@pytest.fixture
def dual(monkeypatch):
    repo = InMemoryUserRepository()
    verifier = Mock()
    verifier.verify.return_value = dict(IDENTITY)
    monkeypatch.setattr(router, "user_repository", repo)
    monkeypatch.setattr(router, "login_user_use_case", LoginUser(repo))
    monkeypatch.setattr(router, "login_with_google_use_case", LoginWithGoogle(repo, verifier))
    monkeypatch.setattr(router, "session_cache", TTLCache(30))
    return TestClient(app), repo, verifier


def google(client):
    response = client.post("/v1/auth/institutional", json={"credential": "verified-google-token"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def change(client, token, password=PASSWORD, current=None):
    return client.post("/v1/auth/change-password", headers=headers(token), json={"current_password": current, "new_password": password, "new_password_confirm": password})


def password_login(client, password=PASSWORD):
    return client.post("/v1/auth/login", json={"username": IDENTITY["email"], "password": password})


def ready_account(client):
    token = google(client)
    assert change(client, token).status_code == 200
    return google(client)


def admin_token(repo):
    manager = repo.save_with_password(User(username="access@ucb.edu.bo", role="Administrador de Accesos", permissions=["consultar_usuarios", "reiniciar_credenciales", "desbloquear_usuarios", "modificar_usuarios"]), "ManagerSecure2026!")
    return LoginUser(repo).execute(manager.username, "ManagerSecure2026!")


def test_operational_admin_keeps_loan_directory_but_cannot_manage_accounts(dual):
    client, repo, _ = dual
    ready_account(client)
    target = repo.get_by_username(IDENTITY['email'])
    repo.save_with_password(User(username='operations@ucb.edu.bo', role='Administrador',
                                 permissions=['gestionar_inventario','gestionar_prestamos','gestionar_stock']), PASSWORD)
    token = LoginUser(repo).execute('operations@ucb.edu.bo', PASSWORD)
    assert client.get('/v1/users/', headers=headers(token)).status_code == 200
    assert client.put(f'/v1/users/{target.id}', headers=headers(token), json={'name':'No autorizado'}).status_code == 403
    assert client.post(f'/v1/users/{target.id}/reset-password', headers=headers(token)).status_code == 403
    assert client.post(f'/v1/users/{target.id}/unlock', headers=headers(token)).status_code == 403
    assert client.delete(f'/v1/users/{target.id}', headers=headers(token)).status_code == 403


def test_first_google_login_requires_password_and_both_methods_share_identity(dual):
    client, repo, _ = dual
    token = google(client)
    claims = decode_token(token)
    assert claims["must_change_password"] is True
    assert claims["auth_method"] == "google"
    account = client.get("/v1/users/me", headers=headers(token)).json()
    assert account["google_linked"] is True
    assert account["local_password_enabled"] is False
    assert account["can_reset_password_with_google"] is True
    assert client.get("/v1/users/", headers=headers(token)).status_code == 403
    assert password_login(client).status_code == 401
    established = change(client, token)
    assert established.status_code == 200
    renewed_token = established.json()["access_token"]
    renewed = decode_token(renewed_token)
    assert renewed["must_change_password"] is False
    assert renewed["session_version"] == claims["session_version"] + 1
    assert renewed["user_id"] == account["id"]
    assert renewed["jti"] != claims["jti"]
    assert client.get("/v1/users/me", headers=headers(renewed_token)).status_code == 200
    assert client.get("/v1/auth/validate", headers=headers(renewed_token)).json()["must_change_password"] is False
    assert client.get("/v1/users/me", headers=headers(token)).status_code == 401
    local = password_login(client)
    assert local.status_code == 200
    assert decode_token(local.json()["access_token"])["user_id"] == account["id"]
    saved = repo.get_by_id(account["id"])
    assert datetime.fromisoformat(saved.password_expires_at) - datetime.fromisoformat(saved.password_changed_at) == timedelta(days=90)
    original = (saved.hashed_password, saved.password_changed_at, saved.password_expires_at, saved.role, saved.user_code)
    again = google(client)
    assert decode_token(again)["must_change_password"] is False
    saved = repo.get_by_id(account["id"])
    assert original == (saved.hashed_password, saved.password_changed_at, saved.password_expires_at, saved.role, saved.user_code)
    assert saved.auth_provider == "hybrid"
    assert len(repo.list_all()) == 1
    assert password_login(client).status_code == 200


@pytest.mark.parametrize("invalid", ["short1!", "lowercase2026!", "UPPERCASE2026!", "MissingNumbers!!", "NoSymbolPass2026"])
def test_all_five_password_requirements_apply_to_google_setup(dual, invalid):
    client, repo, _ = dual
    token = google(client)
    assert change(client, token, invalid).status_code == (422 if len(invalid) < 12 else 400)
    assert repo.get_by_username(IDENTITY["email"]).auth_provider == "google"


def test_google_recovers_forgotten_password_without_old_password(dual):
    client, repo, _ = dual
    token = ready_account(client)
    account = repo.get_by_username(IDENTITY["email"])
    identity = (account.id, account.role, account.user_code)
    assert change(client, token, PASSWORD).status_code == 409
    assert change(client, token, NEXT_PASSWORD).status_code == 204
    assert password_login(client, PASSWORD).status_code == 401
    assert password_login(client, NEXT_PASSWORD).status_code == 200
    account = repo.get_by_username(IDENTITY["email"])
    assert identity == (account.id, account.role, account.user_code)
    assert len(repo.list_password_hashes(account.id)) == 2
    assert PASSWORD not in str(repo.list_security_records("security_audit_event"))


def test_third_failure_blocks_both_methods_and_revokes_existing_session(dual):
    client, repo, _ = dual
    token = ready_account(client)
    for code in (401, 401, 423):
        response = password_login(client, "IncorrectPassword2026!")
        assert response.status_code == code
    assert "Google" in response.json()["detail"]
    assert "Administrador de Accesos" in response.json()["detail"]
    assert password_login(client).status_code == 423
    assert client.post("/v1/auth/institutional", json={"credential": "google"}).status_code == 423
    assert client.get("/v1/users/me", headers=headers(token)).status_code == 401
    assert change(client, token, NEXT_PASSWORD).status_code == 401
    account = repo.get_by_username(IDENTITY["email"])
    unlocked = client.post(f"/v1/users/{account.id}/unlock", headers=headers(admin_token(repo)))
    assert unlocked.status_code == 200
    assert password_login(client).status_code == 200
    assert google(client)


def test_administrator_can_reset_google_or_hybrid_without_breaking_sso(dual):
    client, repo, _ = dual
    old = google(client)
    account = repo.get_by_username(IDENTITY["email"])
    response = client.post(f"/v1/users/{account.id}/reset-password", headers=headers(admin_token(repo)))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    reset_account = repo.get_by_id(account.id)
    assert reset_account.session_version == decode_token(old)["session_version"] + 1
    assert datetime.fromisoformat(reset_account.password_expires_at) - datetime.fromisoformat(reset_account.password_changed_at) == timedelta(days=90)
    temporary = response.json()["temporary_password"]
    local = password_login(client, temporary)
    assert local.status_code == 200
    assert decode_token(local.json()["access_token"])["must_change_password"] is True
    assert change(client, old).status_code == 401
    token = google(client)
    assert change(client, token).status_code == 204
    assert password_login(client).status_code == 200
    assert repo.get_by_username(IDENTITY["email"]).google_sub == IDENTITY["google_sub"]


@pytest.mark.parametrize("method,age,sub", [("google", 301, IDENTITY["google_sub"]), ("password", 0, IDENTITY["google_sub"]), ("google", 0, "other-google-account")])
def test_recovery_requires_recent_google_session_bound_to_same_identity(dual, method, age, sub):
    client, repo, _ = dual
    ready_account(client)
    account = repo.get_by_username(IDENTITY["email"])
    token = create_access_token(subject=account.username, extra_claims={"session_version": account.session_version, "auth_method": method, "auth_time": int(datetime.now(timezone.utc).timestamp()) - age, "google_sub": sub})
    assert change(client, token, NEXT_PASSWORD).status_code == 403
    assert password_login(client).status_code == 200


def test_local_session_requires_current_password_and_respects_history(dual):
    client, _, _ = dual
    ready_account(client)
    token = password_login(client).json()["access_token"]
    assert change(client, token, NEXT_PASSWORD).status_code == 403
    assert change(client, token, NEXT_PASSWORD, "wrong").status_code == 400
    assert change(client, token, NEXT_PASSWORD, PASSWORD).status_code == 204
    token = password_login(client, NEXT_PASSWORD).json()["access_token"]
    assert change(client, token, PASSWORD, NEXT_PASSWORD).status_code == 409


def test_first_link_of_legacy_local_account_preserves_role_and_password(dual):
    client, repo, _ = dual
    legacy = repo.save_with_password(User(username=IDENTITY["email"], role="Docente", user_code="UCB-2026-ABCDEF01"), PASSWORD)
    token = google(client)
    linked = repo.get_by_username(IDENTITY["email"])
    assert (linked.id, linked.role, linked.user_code, linked.hashed_password) == (legacy.id, "Docente", legacy.user_code, legacy.hashed_password)
    assert decode_token(token)["must_change_password"] is True
    assert change(client, token, PASSWORD).status_code == 409
    assert change(client, token, NEXT_PASSWORD).status_code == 204
    assert password_login(client, NEXT_PASSWORD).status_code == 200


def test_expired_password_forces_change_even_after_google_login(dual):
    client, repo, _ = dual
    ready_account(client)
    account = repo.get_by_username(IDENTITY["email"])
    account.password_expires_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    repo.save(account)
    token = google(client)
    assert decode_token(token)["must_change_password"] is True
    assert change(client, token, NEXT_PASSWORD).status_code == 204


def test_google_binding_and_institutional_domain_cannot_be_substituted(dual):
    client, repo, verifier = dual
    ready_account(client)
    verifier.verify.return_value = {**IDENTITY, "google_sub": "attacker-sub"}
    assert client.post("/v1/auth/institutional", json={"credential": "google"}).status_code == 401
    verifier.verify.return_value = {**IDENTITY, "email": "external@gmail.com"}
    assert client.post("/v1/auth/institutional", json={"credential": "google"}).status_code == 401
    verifier.verify.return_value = {**IDENTITY, "email": "different@ucb.edu.bo"}
    assert client.post("/v1/auth/institutional", json={"credential": "google"}).status_code == 401
    assert len(repo.list_all()) == 1


def test_manual_registration_is_removed_even_for_administrator(dual):
    client, repo, _ = dual
    manager = admin_token(repo)
    assert client.post("/v1/users/", headers=headers(manager), json={"username": "new@ucb.edu.bo", "name": "New"}).status_code == 405
    assert client.post("/v1/auth/register", json={"username": "new@ucb.edu.bo", "password": PASSWORD}).status_code == 404
    assert len(repo.list_all()) == 1


def test_concurrent_wrong_passwords_are_counted_in_same_worker(dual):
    _, repo, _ = dual
    repo.save_with_password(User(username=IDENTITY["email"]), PASSWORD)
    login = LoginUser(repo)
    def fail(_):
        try:
            login.execute(IDENTITY["email"], "WrongPassword2026!")
        except ValueError as exc:
            return isinstance(exc, AccountLockedError)
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sum(pool.map(fail, range(3))) == 1
    assert repo.get_by_username(IDENTITY["email"]).failed_login_attempts == 3


def test_google_success_does_not_clear_previous_failed_password_attempts(dual):
    client, repo, _ = dual
    ready_account(client)
    assert password_login(client, "IncorrectPass2026!").status_code == 401
    assert google(client)
    assert repo.get_by_username(IDENTITY["email"]).failed_login_attempts == 1
    assert password_login(client, "IncorrectPass2026!").status_code == 401
    assert password_login(client, "IncorrectPass2026!").status_code == 423


def test_administrative_profile_update_preserves_linked_identity(dual):
    client, repo, _ = dual
    ready_account(client)
    account = repo.get_by_username(IDENTITY["email"])
    manager = admin_token(repo)
    updated = client.put(f"/v1/users/{account.id}", headers=headers(manager), json={"name": "Nombre corregido"})
    assert updated.status_code == 200
    assert updated.json()["google_linked"] is True
    assert password_login(client).status_code == 200
    assert client.put(f"/v1/users/{account.id}", headers=headers(manager), json={"username": "other@ucb.edu.bo"}).status_code == 409


def test_inactive_account_cannot_enter_by_either_method(dual):
    client, repo, _ = dual
    ready_account(client)
    account = repo.get_by_username(IDENTITY["email"])
    account.is_active = False
    repo.save(account)
    assert password_login(client).status_code == 401
    assert client.post("/v1/auth/institutional", json={"credential": "google"}).status_code == 401
