from app.core.config import settings
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository


class RegisterUser:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def execute(self, username: str, password: str) -> User:
        normalized_username = username.lower().strip()
        if not normalized_username.endswith(settings.institutional_email_domain):
            raise ValueError("Credenciales incorrectas")

        if self.repository.get_by_username(normalized_username):
            raise ValueError("El usuario ya existe")

        user = User(
            username=normalized_username,
            name=normalized_username.split("@")[0],
        )
        return self.repository.save_with_password(user, password)
