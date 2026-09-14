"""Who may move a flag, and under what guard.

Dev is cheap to get wrong, so anyone who holds the tool at contributor level
moves it directly. Prod is not: it takes a proposal and a second, different
person, and the apply is bound to the value that was proposed against.
"""

from __future__ import annotations

from ..models import User
from .models import ChangeStatus, Environment, FlagChangeRequest, FlagState


class FlagDenied(Exception):
    def __init__(self, reason: str, status_code: int = 403) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


def check_direct_change(environment: Environment) -> None:
    """Prod never moves without a proposal, whatever the caller holds."""
    if environment is Environment.prod:
        raise FlagDenied("prod_requires_request", status_code=400)


def check_can_decide(viewer: User, request: FlagChangeRequest, state: FlagState) -> None:
    """Maker-checker, enforced here rather than by hiding a button.

    Order matters: the self-approval rule is checked before staleness so a
    requester poking their own proposal never learns anything about it.
    """
    if request.status is not ChangeStatus.pending:
        raise FlagDenied("already_decided", status_code=409)
    if request.requested_by == viewer.id:
        raise FlagDenied("cannot_approve_own_request")
    if state.enabled != request.from_value:
        # Someone moved prod since this was proposed. Applying `to_value` now
        # would overwrite a change nobody reviewed against.
        raise FlagDenied("stale_request", status_code=409)


def check_can_withdraw(viewer: User, request: FlagChangeRequest) -> None:
    if request.status is not ChangeStatus.pending:
        raise FlagDenied("already_decided", status_code=409)
    if request.requested_by != viewer.id:
        raise FlagDenied("not_your_request")
