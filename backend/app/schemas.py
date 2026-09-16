from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import Action, Reason, Role, Status


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


class LoginOut(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut


class EventOut(BaseModel):
    id: int
    action: Action
    comment: str
    created_at: datetime
    actor: UserOut


class RequestOut(BaseModel):
    id: int
    customer_id: str
    customer_name: str
    order_id: str
    reason: Reason
    amount_cents: int
    currency: str
    note: str
    status: Status
    risk_flags: list[str]
    requires_admin: bool
    created_at: datetime
    decided_at: datetime | None
    submitter: UserOut
    decider: UserOut | None
    can_decide: bool
    decide_blocked_reason: str | None
    age_hours: float
    aging: str | None
    unassigned: bool


class RequestPage(BaseModel):
    items: list[RequestOut]
    total: int
    limit: int
    offset: int


class RequestDetailOut(RequestOut):
    events: list[EventOut]


class RequestCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=40)
    customer_name: str = Field(min_length=1, max_length=120)
    order_id: str = Field(min_length=1, max_length=40)
    reason: Reason
    amount_cents: int = Field(gt=0, le=100_000_000)
    note: str = Field(default="", max_length=2000)
    idempotency_key: str | None = Field(default=None, max_length=64)


class DecisionIn(BaseModel):
    action: Action
    comment: str = Field(default="", max_length=2000)
    confirm_risk: bool = False
