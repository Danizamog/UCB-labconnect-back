import secrets

from app.domain.entities.user import User
from app.infrastructure.security.password import hash_password, verify_password


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._data: dict[str, User] = {}
        self._security_data: dict[str, list[dict]] = {}

    def get_by_id(self, user_id: str) -> User | None:
        for user in self._data.values():
            if user.id == user_id:
                return user
        return None

    def list_all(self) -> list[User]:
        return list(self._data.values())

    def list_paginated(self, page: int, per_page: int) -> tuple[list[User], int]:
        all_users = list(self._data.values())
        safe_page = max(1, page)
        safe_per_page = max(1, per_page)
        start = (safe_page - 1) * safe_per_page
        end = start + safe_per_page
        return all_users[start:end], len(all_users)

    def get_by_username(self, username: str) -> User | None:
        return self._data.get(username)

    def get_by_google_sub(self, google_sub: str) -> User | None:
        return next((user for user in self._data.values() if user.google_sub == google_sub), None)

    def save(self, user: User) -> User:
        self._data[user.username] = user
        return user

    def save_with_password(self, user: User, password: str) -> User:
        stored_user = User(
            id=user.id or secrets.token_hex(8),
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
            auth_provider=user.auth_provider,
            google_sub=user.google_sub,
            password_changed_at=user.password_changed_at,
            session_version=user.session_version,
            security_locked=user.security_locked,
            user_code=user.user_code,
            failed_login_attempts=user.failed_login_attempts,
            locked_at=user.locked_at,
            password_expires_at=user.password_expires_at,
            must_change_password=user.must_change_password,
        )
        self._data[stored_user.username] = stored_user
        return stored_user

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.get_by_username(username)
        if not user or not user.hashed_password or not verify_password(password, user.hashed_password):
            return None
        return user

    def change_password(self, user: User, password: str) -> User:
        return self.save_with_password(user, password)

    def list_security_records(self, collection: str, page: int = 1, per_page: int = 100) -> list[dict]:
        records = self._security_data.get(collection, [])
        start = (max(1, page) - 1) * max(1, per_page)
        return records[start:start + max(1, per_page)]

    def create_security_record(self, collection: str, payload: dict) -> None:
        self._security_data.setdefault(collection, []).insert(0, dict(payload))

    def revoke_security_sessions(self, user_id: str, reason: str) -> None:
        for record in self._security_data.get("auth_session", []):
            if record.get("user_id") == user_id and record.get("status") == "active":
                record.update({"status": "revoked", "reason": reason})

    def list_password_hashes(self, user_id: str, limit: int = 5) -> list[str]:
        return [str(item.get("password_hash") or "") for item in self._security_data.get("password_history", []) if item.get("user_id") == user_id][:limit]

    def record_password_hash(self, user_id: str, password_hash: str, reason: str) -> None:
        self.create_security_record("password_history", {"user_id": user_id, "password_hash": password_hash, "reason": reason})
