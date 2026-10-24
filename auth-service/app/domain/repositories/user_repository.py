from typing import Protocol

from app.domain.entities.user import User


class UserRepository(Protocol):
    def get_by_id(self, user_id: str) -> User | None:
        ...

    def list_all(self) -> list[User]:
        ...

    def list_paginated(self, page: int, per_page: int) -> tuple[list[User], int]:
        ...

    def get_by_username(self, username: str) -> User | None:
        ...

    def get_by_google_sub(self, google_sub: str) -> User | None:
        ...

    def save(self, user: User) -> User:
        ...

    def save_with_password(self, user: User, password: str) -> User:
        ...

    def authenticate(self, username: str, password: str) -> User | None:
        ...

    def change_password(self, user: User, password: str) -> User:
        ...

    def list_security_records(self, collection: str, page: int = 1, per_page: int = 100) -> list[dict]:
        ...

    def create_security_record(self, collection: str, payload: dict) -> None:
        ...

    def revoke_security_sessions(self, user_id: str, reason: str) -> None:
        ...

    def list_password_hashes(self, user_id: str, limit: int = 5) -> list[str]:
        ...

    def record_password_hash(self, user_id: str, password_hash: str, reason: str) -> None:
        ...
