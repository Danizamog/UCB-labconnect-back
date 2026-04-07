from dataclasses import dataclass
from dataclasses import field


@dataclass
class User:
    username: str
    hashed_password: str = ""
    id: str | None = None
    name: str | None = None
    role: str | None = None
    profile_type: str | None = None
    phone: str | None = None
    academic_page: str | None = None
    faculty: str | None = None
    career: str | None = None
    student_code: str | None = None
    campus: str | None = None
    bio: str | None = None
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None
    permissions: list[str] = field(default_factory=list)
