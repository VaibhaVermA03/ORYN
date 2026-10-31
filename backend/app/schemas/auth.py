from __future__ import annotations

import re
import unicodedata
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_COMMON_PASSWORDS = {
    "password123", "1234567890", "qwerty12345", "iloveyou123", "password1234",
    "administrator", "welcome12345", "letmein12345", "passw0rd1234",
}


def normalize_email(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().lower()


def validate_password_strength(password: str, email: str | None = None) -> str:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common")
    if len(set(password)) < 4:
        raise ValueError("Password is too repetitive")
    if email and email.split("@")[0] and password.lower() == email.split("@")[0].lower():
        raise ValueError("Password must not match your email")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d|[^A-Za-z0-9]", password)):
        raise ValueError("Password must include letters and at least one number or symbol")
    return password


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("email", mode="after")
    @classmethod
    def _norm_email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("display_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Display name is required")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return validate_password_strength(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="after")
    @classmethod
    def _norm_email(cls, v: str) -> str:
        return normalize_email(v)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: str
    email_verified: bool
    has_password: bool
    google_linked: bool


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Display name is required")
        return v


class LinkIntentResponse(BaseModel):
    link_token: str
    expires_in: int
