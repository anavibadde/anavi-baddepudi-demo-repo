from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..models import Base, User, utcnow


class Environment(str, enum.Enum):
    dev = "dev"
    prod = "prod"


class ChangeStatus(str, enum.Enum):
    pending = "pending"
    applied = "applied"
    rejected = "rejected"
    withdrawn = "withdrawn"


class FlagAction(str, enum.Enum):
    set_directly = "set_directly"
    proposed = "proposed"
    applied = "applied"
    rejected = "rejected"
    withdrawn = "withdrawn"


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    states: Mapped[list[FlagState]] = relationship(
        back_populates="flag", cascade="all, delete-orphan"
    )


class FlagState(Base):
    """The configuration itself — what the demo surface reads.

    One row per flag per environment: this is the thing an approval actually
    writes, which is what separates this tool from the record-only workflows.
    """

    __tablename__ = "flag_states"
    __table_args__ = (UniqueConstraint("flag_id", "environment", name="uq_flag_state_env"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    flag_id: Mapped[int] = mapped_column(ForeignKey("feature_flags.id"), index=True)
    environment: Mapped[Environment] = mapped_column(Enum(Environment), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    flag: Mapped[FeatureFlag] = relationship(back_populates="states")
    updater: Mapped[User | None] = relationship()


class FlagChangeRequest(Base):
    """A proposed production change, bound to the value it was proposed against.

    `from_value` is the guard: prod moving underneath a pending request makes
    the approval refuse rather than silently overwrite whoever moved it.
    """

    __tablename__ = "flag_change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    flag_id: Mapped[int] = mapped_column(ForeignKey("feature_flags.id"), index=True)
    environment: Mapped[Environment] = mapped_column(Enum(Environment), index=True)
    from_value: Mapped[bool] = mapped_column(Boolean)
    to_value: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ChangeStatus] = mapped_column(
        Enum(ChangeStatus), default=ChangeStatus.pending, index=True
    )
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")

    flag: Mapped[FeatureFlag] = relationship()
    requester: Mapped[User] = relationship(foreign_keys=[requested_by])
    decider: Mapped[User | None] = relationship(foreign_keys=[decided_by])


class FlagEvent(Base):
    """Append-only history. Every value a flag has ever held is recoverable from
    this table; the state rows are only the current rollup."""

    __tablename__ = "flag_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    flag_id: Mapped[int] = mapped_column(ForeignKey("feature_flags.id"), index=True)
    environment: Mapped[Environment] = mapped_column(Enum(Environment))
    action: Mapped[FlagAction] = mapped_column(Enum(FlagAction))
    from_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    to_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("flag_change_requests.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    flag: Mapped[FeatureFlag] = relationship()
    actor: Mapped[User] = relationship()
