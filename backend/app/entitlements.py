"""Which tools a person can open.

The platform has one login and one users table, but a shared login is not a
shared key: every tool is opened by an explicit grant, and the home page only
lists what the caller actually holds.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .models import RANK, AppRole, AppSlug, Entitlement, Role, User


@dataclass(frozen=True)
class AppInfo:
    slug: AppSlug
    name: str
    description: str
    path: str


REGISTRY: tuple[AppInfo, ...] = (
    AppInfo(
        slug=AppSlug.refunds,
        name="Refund review",
        description="Customer refund requests, risk flags and approvals.",
        path="/refunds",
    ),
    AppInfo(
        slug=AppSlug.flags,
        name="Feature flags",
        description="Dev toggles, production change requests and approvals.",
        path="/flags",
    ),
    AppInfo(
        slug=AppSlug.kyc,
        name="KYC review",
        description="Shared applicant queue with claiming and two-person sign-off.",
        path="/kyc",
    ),
)

APPS: dict[AppSlug, AppInfo] = {info.slug: info for info in REGISTRY}


def entitlement_for(session: DbSession, user: User, app: AppSlug) -> Entitlement | None:
    return session.scalar(
        select(Entitlement).where(Entitlement.user_id == user.id, Entitlement.app == app)
    )


def effective_role(session: DbSession, user: User, app: AppSlug) -> AppRole | None:
    """The caller's role inside one tool, or None when they hold no grant.

    Platform admins hold every tool: a demo with an admin who can be locked out
    of the thing they administer is a demo of nothing.
    """
    if user.role is Role.admin:
        return AppRole.admin
    grant = entitlement_for(session, user, app)
    return None if grant is None else grant.app_role


def holds(role: AppRole | None, minimum: AppRole) -> bool:
    return role is not None and RANK[role] >= RANK[minimum]


def apps_for(session: DbSession, user: User) -> list[tuple[AppInfo, AppRole]]:
    held = []
    for info in REGISTRY:
        role = effective_role(session, user, info.slug)
        if role is not None:
            held.append((info, role))
    return held


def grant(session: DbSession, user: User, app: AppSlug, app_role: AppRole) -> Entitlement:
    existing = entitlement_for(session, user, app)
    if existing is not None:
        existing.app_role = app_role
        return existing
    record = Entitlement(user_id=user.id, app=app, app_role=app_role)
    session.add(record)
    return record
