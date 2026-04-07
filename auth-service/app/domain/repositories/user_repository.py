from typing import Protocol

from app.domain.entities.user import User


class UserRepository(Protocol):
    def get_by_id(self, user_id: str) -> User | None:
        ...

    def list_all(self) -> list[User]:
        ...

    def get_by_username(self, username: str) -> User | None:
        ...

    def save(self, user: User) -> User:
        ...

    def save_with_password(self, user: User, password: str) -> User:
        ...

    def authenticate(self, username: str, password: str) -> User | None:
        ...
