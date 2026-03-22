from app.domain.entities.user import User


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._data: dict[str, User] = {}

    def get_by_username(self, username: str) -> User | None:
        return self._data.get(username)

    def save(self, user: User) -> None:
        self._data[user.username] = user
