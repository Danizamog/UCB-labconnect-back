import pytest

from app.core.local_test_accounts import seed_local_test_accounts
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository


TEST_PASSWORD = "LabConnectPrueba2026!"


def test_seed_local_test_accounts_creates_login_ready_users():
    repository = InMemoryUserRepository()
    emails = "marcia.miranda@ucb.edu.bo,laura.perez.e@ucb.edu.bo"

    assert seed_local_test_accounts(repository, emails, TEST_PASSWORD) == 2
    assert repository.authenticate("marcia.miranda@ucb.edu.bo", TEST_PASSWORD) is not None
    assert repository.authenticate("laura.perez.e@ucb.edu.bo", TEST_PASSWORD) is not None


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


def test_seed_local_test_accounts_rejects_persistent_repositories():
    class PersistentRepository:
        pass

    with pytest.raises(RuntimeError, match="almacenamiento local en memoria"):
        seed_local_test_accounts(PersistentRepository(), "test@ucb.edu.bo", TEST_PASSWORD)


def test_seed_local_test_accounts_rejects_non_institutional_email():
    with pytest.raises(ValueError, match="Correo institucional no válido"):
        seed_local_test_accounts(InMemoryUserRepository(), "test@example.com", TEST_PASSWORD)
