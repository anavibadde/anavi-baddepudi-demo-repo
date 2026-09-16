from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import AppRole, AppSlug, Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: Role
    manager_id: int | None
    is_active: bool


class UserUpdate(BaseModel):
    role: Role | None = None
    manager_id: int | None = None
    is_active: bool | None = None


class LoginIn(BaseModel):
    user_id: int
    password: str = Field(min_length=1, max_length=200)


class SwitchIn(BaseModel):
    user_id: int


class LoginOut(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut


class AppOut(BaseModel):
    slug: AppSlug
    name: str
    description: str
    path: str
    app_role: AppRole
