from typing import Optional
from pydantic import BaseModel, model_validator


class LoginRequest(BaseModel):
    account: Optional[str] = None  # Email or Phone number
    email: Optional[str] = None
    password: str

    @model_validator(mode="after")
    def validate_account(self):
        if not self.account and self.email:
            self.account = self.email
        if not self.account:
            raise ValueError("account or email field is required for login")
        return self


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LogoutRequest(BaseModel):
    refresh_token: str
