from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str
    captcha_token: str | None = Field(default=None, max_length=8192)


class LoginCaptchaConfigResponse(BaseModel):
    enabled: bool
    configured: bool
    site_key: str | None = None


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


class ChangePasswordRequest(BaseModel):
    current_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)
    new_password_confirm: str = Field(min_length=12, max_length=128)
