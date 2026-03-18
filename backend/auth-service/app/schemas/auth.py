from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    password: str
    role: str = "user"


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    email: EmailStr
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserOut

class GoogleTokenIn(BaseModel):
    credential: str