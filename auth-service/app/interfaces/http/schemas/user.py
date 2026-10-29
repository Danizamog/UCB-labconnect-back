from pydantic import BaseModel, Field


class UserProfileBase(BaseModel):
    name: str | None = None
    profile_type: str | None = None
    phone: str | None = None
    academic_page: str | None = None
    faculty: str | None = None
    career: str | None = None
    student_code: str | None = None
    campus: str | None = None
    bio: str | None = None
    is_active: bool | None = None


class UserProfileUpdateRequest(UserProfileBase):
    username: str | None = Field(default=None, min_length=5)


class UserProfileResponse(BaseModel):
    id: str | None = None
    username: str
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
    auth_provider: str = "local"
    password_changed_at: str | None = None
    user_code: str | None = None
    security_locked: bool = False
    failed_login_attempts: int = 0
    locked_at: str | None = None
    password_expires_at: str | None = None
    must_change_password: bool = False
    google_linked: bool = False
    local_password_enabled: bool = False
    can_reset_password_with_google: bool = False
    auth_method: str | None = None
    google_verification_expires_at: int | None = None


class PasswordResetResponse(BaseModel):
    temporary_password: str
    must_change_password: bool = True


class OperationalUserResponse(BaseModel):
    id: str
    username: str
    name: str | None = None
    role: str | None = None
    is_active: bool = True
    student_code: str | None = None
