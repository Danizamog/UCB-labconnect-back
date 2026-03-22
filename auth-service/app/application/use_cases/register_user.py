from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.security.password import hash_password


class RegisterUser:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def execute(self, username: str, password: str) -> User:
        normalized_username = username.lower().strip()
        if self.repository.get_by_username(normalized_username):
            raise ValueError("El usuario ya existe")

        user = User(
            username=normalized_username,
            hashed_password=hash_password(password),
        )
        self.repository.save(user)
        return user
