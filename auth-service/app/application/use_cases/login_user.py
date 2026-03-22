from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.security.password import verify_password
from app.infrastructure.security.token_provider import create_access_token


class LoginUser:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def execute(self, username: str, password: str) -> str:
        normalized_username = username.lower().strip()
        user = self.repository.get_by_username(normalized_username)
        if not user or not verify_password(password, user.hashed_password):
            raise ValueError("Credenciales inválidas")

        return create_access_token(subject=user.username)
