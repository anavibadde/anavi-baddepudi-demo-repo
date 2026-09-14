"""Authorization and policy rules.

Every read and write goes through these functions. The UI mirrors them for
affordances only; the server is the enforcement point.
"""

from __future__ import annotations

from sqlalchemy import Select, or_, select

from .models import Action, RefundRequest, Role, Status, User
from .risk import requires_admin, requires_confirmation


def visible_requests(viewer: User) -> Select[tuple[RefundRequest]]:
    """Requests the viewer may list: their own, plus their direct reports'."""
    stmt = select(RefundRequest)
    if viewer.role is Role.admin:
        return stmt
    reports = select(User.id).where(User.manager_id == viewer.id).scalar_subquery()
    return stmt.where(
        or_(RefundRequest.created_by == viewer.id, RefundRequest.created_by.in_(reports))
    )


def can_view(viewer: User, request: RefundRequest, submitter: User) -> bool:
    if viewer.role is Role.admin:
        return True
    if request.created_by == viewer.id:
        return True
    return submitter.manager_id == viewer.id


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
