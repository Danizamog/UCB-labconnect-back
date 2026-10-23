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


class UserProfileCreateRequest(UserProfileBase):
    username: str | None = Field(default=None, min_length=5)
    name: str = Field(min_length=2)
    profile_type: str = "student"
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    paternal_surname: str | None = Field(default=None, min_length=1, max_length=80)
    maternal_surname: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool = True


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


class PasswordResetResponse(BaseModel):
    temporary_password: str
    must_change_password: bool = True


class UserProfileCreatedResponse(UserProfileResponse):
    temporary_password: str
