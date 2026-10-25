import pytest
from fastapi.testclient import TestClient

from app.core.local_test_accounts import seed_local_test_accounts
from app.domain.entities.user import User
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository


TEST_PASSWORD = "LabConnectPrueba2026!"


def test_seed_local_test_accounts_creates_login_ready_students():
    repository = InMemoryUserRepository()

    seeded_count = seed_local_test_accounts(
        repository,
        "  MARCIA.MIRANDA@UCB.EDU.BO, laura.perez.e@ucb.edu.bo ",
        TEST_PASSWORD,
    )

    assert seeded_count == 2
    student = repository.authenticate("marcia.miranda@ucb.edu.bo", TEST_PASSWORD)
    assert student is not None
    assert student.name == "Marcia Miranda"
    assert student.role == "Estudiante"
    assert student.profile_type == "student"
    assert repository.authenticate("laura.perez.e@ucb.edu.bo", "WrongPassword2026!") is None


def test_seed_local_test_accounts_creates_teacher_with_teacher_profile():
    repository = InMemoryUserRepository()

    assert seed_local_test_accounts(
        repository,
        "",
        TEST_PASSWORD,
        "lperedo.q@ucb.edu.bo",
    ) == 1
    teacher = repository.authenticate("lperedo.q@ucb.edu.bo", TEST_PASSWORD)

    assert teacher is not None
    assert teacher.role == "Docente"
    assert teacher.profile_type == "teacher"


def test_seed_local_test_accounts_runs_during_auth_service_startup(monkeypatch):
    from app import main
    from app.application import container

    repository = InMemoryUserRepository()
    monkeypatch.setattr(main, "user_repository", repository)
    monkeypatch.setattr(container.login_user_use_case, "repository", repository)
    monkeypatch.setattr(main.settings, "local_test_account_emails", "startup.test@ucb.edu.bo")
    monkeypatch.setattr(main.settings, "local_test_teacher_emails", "")
    monkeypatch.setattr(main.settings, "local_test_account_password", TEST_PASSWORD)

    with TestClient(main.app) as client:
        assert repository.authenticate("startup.test@ucb.edu.bo", TEST_PASSWORD) is not None
        response = client.post(
            "/v1/auth/login",
            json={"username": "startup.test@ucb.edu.bo", "password": TEST_PASSWORD},
        )
        assert response.status_code == 200
        assert response.json()["access_token"]


def test_seed_local_test_accounts_rejects_persistent_repositories():
    class PersistentRepository:
        pass

    with pytest.raises(RuntimeError, match="almacenamiento local en memoria"):
        seed_local_test_accounts(PersistentRepository(), "test@ucb.edu.bo", TEST_PASSWORD)


@pytest.mark.parametrize(
    "email",
    [
        "test@example.com",
        "test@ucb.edu.bo.attacker.example",
        "test @ucb.edu.bo",
        "test@@ucb.edu.bo",
    ],
)
def test_seed_local_test_accounts_rejects_non_institutional_emails(email):
    with pytest.raises(ValueError, match="Correo institucional no válido"):
        seed_local_test_accounts(InMemoryUserRepository(), email, TEST_PASSWORD)


def test_seed_local_test_accounts_rejects_normalized_duplicates_without_partial_write():
    repository = InMemoryUserRepository()

    with pytest.raises(ValueError, match="correos duplicados"):
        seed_local_test_accounts(
            repository,
            "test@ucb.edu.bo, TEST@UCB.EDU.BO",
            TEST_PASSWORD,
        )

    assert repository.list_all() == []


def test_seed_local_test_accounts_rejects_an_existing_account_without_overwriting_it():
    repository = InMemoryUserRepository()
    repository.save_with_password(
        User(username="existing@ucb.edu.bo", name="Existing User"),
        "OriginalPass2026!",
    )

    with pytest.raises(RuntimeError, match="ya existe"):
        seed_local_test_accounts(
            repository,
            "existing@ucb.edu.bo,new@ucb.edu.bo",
            TEST_PASSWORD,
        )

    assert repository.authenticate("existing@ucb.edu.bo", "OriginalPass2026!") is not None
    assert repository.get_by_username("new@ucb.edu.bo") is None


def test_seed_local_test_accounts_requires_password_and_valid_password_policy():
    repository = InMemoryUserRepository()

    with pytest.raises(ValueError, match="es obligatorio"):
        seed_local_test_accounts(repository, "test@ucb.edu.bo", "")
    with pytest.raises(ValueError, match="entre 12 y 128"):
        seed_local_test_accounts(repository, "test@ucb.edu.bo", "short")
    assert repository.list_all() == []


def test_seed_local_test_accounts_rejects_password_without_accounts():
    with pytest.raises(ValueError, match="requiere cuentas locales"):
        seed_local_test_accounts(InMemoryUserRepository(), "", TEST_PASSWORD)


def test_seed_local_test_accounts_is_noop_when_not_configured():
    repository = InMemoryUserRepository()

    assert seed_local_test_accounts(repository, "", "") == 0
    assert repository.list_all() == []
