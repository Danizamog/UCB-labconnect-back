from app.core.config import settings
from app.domain.entities.user import User
from app.domain.password_policy import validate_password
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository


def _is_institutional_email(email: str, configured_domain: str) -> bool:
    if email.count("@") != 1 or any(character.isspace() for character in email):
        return False
    local_part, domain = email.rsplit("@", 1)
    normalized_domain = configured_domain.strip().lower().lstrip("@")
    return bool(local_part and domain == normalized_domain)


def seed_local_test_accounts(
    repository: object,
    raw_emails: str,
    password: str,
    raw_teacher_emails: str = "",
) -> int:
    student_emails = [email.strip().lower() for email in raw_emails.split(",") if email.strip()]
    teacher_emails = [email.strip().lower() for email in raw_teacher_emails.split(",") if email.strip()]
    accounts = [(email, "Estudiante", "student") for email in student_emails]
    accounts.extend((email, "Docente", "teacher") for email in teacher_emails)

    if not accounts:
        if password:
            raise ValueError("LOCAL_TEST_ACCOUNT_PASSWORD requiere cuentas locales de prueba")
        return 0

    if not isinstance(repository, InMemoryUserRepository):
        raise RuntimeError("Las cuentas de prueba solo se permiten con almacenamiento local en memoria")
    if not password:
        raise ValueError("LOCAL_TEST_ACCOUNT_PASSWORD es obligatorio si se configuran cuentas de prueba")

    emails = [email for email, _, _ in accounts]
    if len(set(emails)) != len(emails):
        raise ValueError("La lista de cuentas de prueba contiene correos duplicados")
    for email in emails:
        if not _is_institutional_email(email, settings.institutional_email_domain):
            raise ValueError(f"Correo institucional no válido para prueba: {email}")
        if repository.get_by_username(email):
            raise RuntimeError(f"La cuenta local de prueba ya existe: {email}")
    validate_password(password)

    for email, role, profile_type in accounts:
        name = email.split("@", 1)[0].replace(".", " ").title()
        repository.save_with_password(
            User(username=email, name=name, role=role, profile_type=profile_type),
            password,
        )
    return len(accounts)
