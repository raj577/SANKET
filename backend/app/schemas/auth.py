from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.models.enums import Role
from app.schemas.common import ORMModel


class LoginRequest(ORMModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(ORMModel):
    refresh_token: str = Field(min_length=10)


class LogoutRequest(ORMModel):
    refresh_token: str = Field(min_length=10)


class TokenPairOut(ORMModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORMModel):
    id: uuid.UUID
    name: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime


class UserCreate(ORMModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.USER


class UserUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)
