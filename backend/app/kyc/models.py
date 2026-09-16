from __future__ import annotations

import enum
from datetime import datetime, timedelta

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..models import Base, User, utcnow

CLAIM_TTL = timedelta(hours=4)


class CaseStatus(str, enum.Enum):
    """A KYC case cycles; it is not the one-shot pending → decided of a refund.

    new → claimed → recommended → approved | rejected, and a reviewer who wants
    documents sends it back to new via needs_info.
    """

    new = "new"
    claimed = "claimed"
    recommended = "recommended"
    needs_info = "needs_info"
    approved = "approved"
    rejected = "rejected"


class RiskTier(str, enum.Enum):
    standard = "standard"
    enhanced = "enhanced"


class CaseAction(str, enum.Enum):
    opened = "opened"
    claimed = "claimed"
    released = "released"
    claim_expired = "claim_expired"
    recommended = "recommended"
    info_requested = "info_requested"
    info_supplied = "info_supplied"
    approved = "approved"
    rejected = "rejected"


TERMINAL = (CaseStatus.approved, CaseStatus.rejected)


class KycCase(Base):
    """One applicant under review.

    `claimed_by` is a soft lock on a shared pool, not ownership: it expires so
    an abandoned claim returns to the queue instead of parking the case.
    `recommended_by` is the maker of maker-checker and is kept for the life of
    the case so sign-off can refuse the same person.
    """

    __tablename__ = "kyc_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    applicant_name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(2))
    entity_type: Mapped[str] = mapped_column(String(24))
    risk_tier: Mapped[RiskTier] = mapped_column(Enum(RiskTier), default=RiskTier.standard)
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[CaseStatus] = mapped_column(Enum(CaseStatus), default=CaseStatus.new, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claimed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    recommended_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    recommended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recommendation: Mapped[CaseStatus | None] = mapped_column(Enum(CaseStatus), nullable=True)

    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cycles: Mapped[int] = mapped_column(Integer, default=1)

    claimer: Mapped[User | None] = relationship(foreign_keys=[claimed_by])
    recommender: Mapped[User | None] = relationship(foreign_keys=[recommended_by])
    decider: Mapped[User | None] = relationship(foreign_keys=[decided_by])


class KycEvent(Base):
    """Append-only, and it spans cycles: a case sent back for documents keeps
    every earlier recommendation rather than starting clean."""

    __tablename__ = "kyc_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("kyc_cases.id"), index=True)
    action: Mapped[CaseAction] = mapped_column(Enum(CaseAction))
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    comment: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    actor: Mapped[User | None] = relationship()
