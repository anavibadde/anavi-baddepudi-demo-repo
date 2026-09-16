"""Who may touch a KYC case, and in what order.

Refunds scope by org chart; KYC does not. The queue is a shared pool anyone
holding the tool can work, and the control is maker-checker instead: whoever
recommends an outcome cannot be the one who signs it off.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import User
from .models import TERMINAL, CaseStatus, KycCase, utcnow


class KycDenied(Exception):
    def __init__(self, reason: str, status_code: int = 403) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


def as_utc(value: datetime) -> datetime:
    """SQLite hands timestamps back without a zone."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def claim_expired(case: KycCase, now: datetime | None = None) -> bool:
    """An abandoned claim must not park a case forever, so the lock has a TTL
    and anyone may take an expired one."""
    if case.claimed_by is None or case.claim_expires_at is None:
        return False
    return as_utc(case.claim_expires_at) <= (now or utcnow())


def held_by_someone_else(viewer: User, case: KycCase) -> bool:
    return case.claimed_by is not None and case.claimed_by != viewer.id and not claim_expired(case)


CLAIMABLE = (CaseStatus.new, CaseStatus.claimed)


def check_can_claim(viewer: User, case: KycCase) -> None:
    if case.status in TERMINAL:
        raise KycDenied("already_decided", status_code=409)
    if case.status is CaseStatus.recommended:
        raise KycDenied("awaiting_sign_off", status_code=409)
    if case.status is CaseStatus.needs_info:
        raise KycDenied("awaiting_info", status_code=409)
    if case.claimed_by == viewer.id and not claim_expired(case):
        raise KycDenied("already_yours", status_code=409)
    if held_by_someone_else(viewer, case):
        raise KycDenied("claimed_by_someone_else", status_code=409)


def check_can_release(viewer: User, case: KycCase) -> None:
    if case.claimed_by is None:
        raise KycDenied("not_claimed", status_code=409)
    if case.claimed_by != viewer.id:
        raise KycDenied("not_your_claim")


def check_can_recommend(viewer: User, case: KycCase) -> None:
    """Only the holder of a live claim recommends, so two reviewers cannot
    work the same case into conflicting recommendations."""
    if case.status in TERMINAL:
        raise KycDenied("already_decided", status_code=409)
    if case.status is CaseStatus.recommended:
        raise KycDenied("awaiting_sign_off", status_code=409)
    if case.claimed_by is None or claim_expired(case):
        raise KycDenied("claim_required", status_code=409)
    if case.claimed_by != viewer.id:
        raise KycDenied("not_your_claim")


def check_can_sign_off(viewer: User, case: KycCase) -> None:
    """The checker half. Recommending and signing off are deliberately two
    people, and the backend is where that holds."""
    if case.status in TERMINAL:
        raise KycDenied("already_decided", status_code=409)
    if case.status is not CaseStatus.recommended:
        raise KycDenied("no_recommendation", status_code=409)
    if case.recommended_by == viewer.id:
        raise KycDenied("cannot_sign_off_own_recommendation")
