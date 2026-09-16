from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..models import Base, User, utcnow


class Status(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Action(str, enum.Enum):
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"


class Reason(str, enum.Enum):
    duplicate_charge = "duplicate_charge"
    incorrect_amount = "incorrect_amount"
    item_not_received = "item_not_received"
    item_damaged = "item_damaged"
    cancelled_order = "cancelled_order"
    fraud_dispute = "fraud_dispute"
    other = "other"


class RefundRequest(Base):
    __tablename__ = "refund_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(40), index=True)
    customer_name: Mapped[str] = mapped_column(String(120))
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[Reason] = mapped_column(Enum(Reason))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[Status] = mapped_column(Enum(Status), default=Status.pending, index=True)
    risk_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    submitter: Mapped[User] = relationship(foreign_keys=[created_by])
    decider: Mapped[User | None] = relationship(foreign_keys=[decided_by])
    events: Mapped[list[DecisionEvent]] = relationship(
        back_populates="request", order_by="DecisionEvent.id", cascade="all, delete-orphan"
    )


class DecisionEvent(Base):
    __tablename__ = "decision_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("refund_requests.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[Action] = mapped_column(Enum(Action))
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    request: Mapped[RefundRequest] = relationship(back_populates="events")
    actor: Mapped[User] = relationship()
