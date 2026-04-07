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
    username: str = Field(min_length=5)
    password: str = Field(min_length=8)
    name: str = Field(min_length=2)
    profile_type: str = "student"
    is_active: bool = True


class UserProfileUpdateRequest(UserProfileBase):
    username: str | None = Field(default=None, min_length=5)
    password: str | None = Field(default=None, min_length=8)


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
