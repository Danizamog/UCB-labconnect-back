from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    password: str
    role: str = "student"


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    email: EmailStr
    role: str
    is_active: bool
    phone: str | None = None
    academic_page: str | None = None
    faculty: str | None = None
    career: str | None = None
    student_code: str | None = None
    campus: str | None = None
    bio: str | None = None

    model_config = {"from_attributes": True}


class UserProfileUpdate(BaseModel):
    phone: str | None = None
    academic_page: str | None = None
    faculty: str | None = None
    career: str | None = None
    student_code: str | None = None
    campus: str | None = None
    bio: str | None = None


class UserAdminUpdate(BaseModel):
    full_name: str
    email: EmailStr
    role: str
    is_active: bool
    password: str | None = None
    phone: str | None = None
    academic_page: str | None = None
    faculty: str | None = None
    career: str | None = None
    student_code: str | None = None
    campus: str | None = None
    bio: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserOut

class GoogleTokenIn(BaseModel):
    credential: str
