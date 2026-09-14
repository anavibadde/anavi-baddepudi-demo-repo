from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..schemas import UserOut
from .models import ChangeStatus, Environment, FlagAction


class StateOut(BaseModel):
    environment: Environment
    enabled: bool
    updated_at: datetime
    updated_by: UserOut | None


class ChangeRequestOut(BaseModel):
    id: int
    flag_id: int
    flag_key: str
    environment: Environment
    from_value: bool
    to_value: bool
    reason: str
    status: ChangeStatus
    requester: UserOut
    requested_at: datetime
    decider: UserOut | None
    decided_at: datetime | None
    decision_note: str
    # Prod moved since this was proposed, so approving it would overwrite a
    # change nobody reviewed. Shown, not hidden, so the reviewer knows why.
    stale: bool
    can_decide: bool
    decide_blocked_reason: str | None


class EventOut(BaseModel):
    id: int
    action: FlagAction
    environment: Environment
    from_value: bool | None
    to_value: bool | None
    comment: str
    actor: UserOut
    created_at: datetime


class FlagOut(BaseModel):
    id: int
    key: str
    name: str
    description: str
    states: list[StateOut]
    pending: list[ChangeRequestOut]


class FlagDetailOut(FlagOut):
    events: list[EventOut]


class SetStateIn(BaseModel):
    environment: Environment
    enabled: bool
    reason: str = Field(default="", max_length=500)


class ChangeRequestIn(BaseModel):
    environment: Environment
    from_value: bool
    to_value: bool
    reason: str = Field(default="", max_length=500)


class DecisionIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=500)
