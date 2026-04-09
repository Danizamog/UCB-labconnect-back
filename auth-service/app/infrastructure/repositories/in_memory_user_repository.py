from app.domain.entities.user import User
from app.infrastructure.security.password import hash_password, verify_password


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._data: dict[str, User] = {}

    def get_by_id(self, user_id: str) -> User | None:
        for user in self._data.values():
            if user.id == user_id:
                return user
        return None

    def list_all(self) -> list[User]:
        return list(self._data.values())

    def get_by_username(self, username: str) -> User | None:
        return self._data.get(username)

    def save(self, user: User) -> User:
        self._data[user.username] = user
        return user

    def save_with_password(self, user: User, password: str) -> User:
        stored_user = User(
            id=user.id,
            username=user.username,
            hashed_password=hash_password(password),
            name=user.name,
            role=user.role,
            profile_type=user.profile_type,
            phone=user.phone,
            academic_page=user.academic_page,
            faculty=user.faculty,
            career=user.career,
            student_code=user.student_code,
            campus=user.campus,
            bio=user.bio,
            is_active=user.is_active,
            permissions=list(user.permissions),
        )
        self._data[stored_user.username] = stored_user
        return stored_user

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.get_by_username(username)
        if not user or not user.hashed_password or not verify_password(password, user.hashed_password):
            return None
        return user

    def delete(self, user_id: str) -> bool:
        normalized_id = user_id.strip()
        for username, user in list(self._data.items()):
            if user.id == normalized_id:
                del self._data[username]
                return True
        return False
