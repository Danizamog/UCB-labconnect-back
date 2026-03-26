from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=1)


class InstitutionalLoginRequest(BaseModel):
    credential: str = Field(min_length=1)


class InstitutionalSSOConfigResponse(BaseModel):
    enabled: bool
    provider: str | None = None
    client_id: str | None = None
    button_label: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
