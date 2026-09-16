"""Identity shared by every tool on the platform.

Nothing workflow-specific lives here: a tool's own tables belong in its package
(see `app/refunds/models.py`), so one tool cannot quietly widen another's rules.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    analyst = "analyst"
    manager = "manager"
    admin = "admin"


class AppSlug(str, enum.Enum):
    refunds = "refunds"
    flags = "flags"


class AppRole(str, enum.Enum):
    """How much someone can do inside one tool.

    Deliberately generic — each tool maps these onto its own verbs — and ordered
    by `RANK` below so a check can ask for "at least reviewer".
    """

    viewer = "viewer"
    contributor = "contributor"
    reviewer = "reviewer"
    admin = "admin"


RANK: dict[AppRole, int] = {
    AppRole.viewer: 0,
    AppRole.contributor: 1,
    AppRole.reviewer: 2,
    AppRole.admin: 3,
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    role: Mapped[Role] = mapped_column(Enum(Role))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(200), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    manager: Mapped[User | None] = relationship(remote_side=[id], backref="reports")
    entitlements: Mapped[list[Entitlement]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Entitlement(Base):
    """One person's access to one tool.

    Signing in proves who you are and grants nothing; a row here is what opens a
    tool, and the tool's own rules still apply on top of it.
    """

    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("user_id", "app", name="uq_entitlement_user_app"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    app: Mapped[AppSlug] = mapped_column(Enum(AppSlug), index=True)
    app_role: Mapped[AppRole] = mapped_column(Enum(AppRole), default=AppRole.viewer)

    user: Mapped[User] = relationship(back_populates="entitlements")


class Session(Base):
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()
