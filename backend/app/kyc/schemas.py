from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..schemas import UserOut
from .models import CaseAction, CaseStatus, RiskTier


class CaseOut(BaseModel):
    id: int
    reference: str
    applicant_name: str
    country: str
    entity_type: str
    risk_tier: RiskTier
    summary: str
    status: CaseStatus
    created_at: datetime
    updated_at: datetime
    cycles: int
    claimer: UserOut | None
    claimed_at: datetime | None
    claim_expires_at: datetime | None
    # An abandoned claim still names its holder, so say plainly that the lock
    # has lapsed rather than leaving a stale name on the row.
    claim_expired: bool
    recommender: UserOut | None
    recommendation: CaseStatus | None
    recommended_at: datetime | None
    decider: UserOut | None
    decided_at: datetime | None
    can_claim: bool
    can_recommend: bool
    can_sign_off: bool
    blocked_reason: str | None


class EventOut(BaseModel):
    id: int
    action: CaseAction
    cycle: int
    comment: str
    actor: UserOut | None
    created_at: datetime


class CaseDetailOut(CaseOut):
    events: list[EventOut]


class RecommendIn(BaseModel):
    recommendation: CaseStatus
    note: str = Field(default="", max_length=1000)


class SignOffIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=1000)


class NeedsInfoIn(BaseModel):
    note: str = Field(min_length=1, max_length=1000)


class InfoSuppliedIn(BaseModel):
    note: str = Field(default="", max_length=1000)
