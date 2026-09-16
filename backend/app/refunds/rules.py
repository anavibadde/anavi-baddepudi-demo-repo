"""Authorization and policy rules.

Every read and write goes through these functions. The UI mirrors them for
affordances only; the server is the enforcement point.
"""

from __future__ import annotations

from sqlalchemy import Select, or_, select

from ..models import Role, User
from .models import Action, RefundRequest, Status
from .risk import requires_admin, requires_confirmation


def visible_requests(viewer: User) -> Select[tuple[RefundRequest]]:
    """Requests the viewer may list: their own, their direct reports', and the
    reports of any direct report who has been deactivated."""
    stmt = select(RefundRequest)
    if viewer.role is Role.admin:
        return stmt
    reports = select(User.id).where(User.manager_id == viewer.id).scalar_subquery()
    inactive_reports = (
        select(User.id)
        .where(User.manager_id == viewer.id, User.is_active.is_(False))
        .scalar_subquery()
    )
    inherited = select(User.id).where(User.manager_id.in_(inactive_reports)).scalar_subquery()
    return stmt.where(
        or_(
            RefundRequest.created_by == viewer.id,
            RefundRequest.created_by.in_(reports),
            RefundRequest.created_by.in_(inherited),
        )
    )


def can_view(viewer: User, request: RefundRequest, submitter: User) -> bool:
    if viewer.role is Role.admin:
        return True
    if request.created_by == viewer.id:
        return True
    if submitter.manager_id == viewer.id:
        return True
    # One hop up: a deactivated manager's queue falls to their own manager
    # rather than becoming invisible to everyone but an admin.
    manager = submitter.manager
    return manager is not None and not manager.is_active and manager.manager_id == viewer.id


def reviewer_for(submitter: User) -> User | None:
    """The nearest active person above the submitter who could decide their
    request, or None when the request can only be handled by an admin."""
    seen: set[int] = {submitter.id}
    manager = submitter.manager
    # A bad reorg can point two people at each other; walk defensively.
    while manager is not None and manager.id not in seen:
        if manager.is_active and manager.role is not Role.analyst:
            return manager
        seen.add(manager.id)
        manager = manager.manager
    return None


class DecisionDenied(Exception):
    """Raised with a machine-readable reason when a decision is not permitted."""

    def __init__(self, reason: str, status_code: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


def check_can_decide(
    actor: User,
    request: RefundRequest,
    submitter: User,
    *,
    action: Action,
    confirmed_risk: bool,
) -> None:
    if not can_view(actor, request, submitter):
        raise DecisionDenied("not_found", 404)
    if not actor.is_active:
        raise DecisionDenied("account_deactivated", 403)
    if actor.role is Role.analyst:
        raise DecisionDenied("analysts_cannot_decide", 403)
    if actor.id == request.created_by:
        raise DecisionDenied("cannot_decide_own_request", 403)
    if request.status is not Status.pending:
        raise DecisionDenied("already_decided", 409)
    if action is not Action.approved:
        return
    flags = list(request.risk_flags or [])
    if requires_admin(flags) and actor.role is not Role.admin:
        raise DecisionDenied("admin_approval_required", 403)
    if requires_confirmation(flags) and not confirmed_risk:
        raise DecisionDenied("risk_confirmation_required", 400)
