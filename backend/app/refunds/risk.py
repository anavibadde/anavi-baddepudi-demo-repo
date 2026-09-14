"""Risk flags: cheap heuristics computed once, at submit time.

Flags are stored on the request so the queue can sort by them and so history
shows what the reviewer actually saw, not what today's rules would say.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Reason, RefundRequest, Status

HIGH_VALUE_CENTS = 100_000  # $1,000.00
REPEAT_WINDOW_DAYS = 90
REPEAT_THRESHOLD = 2  # prior refunds for the same customer within the window
BURST_WINDOW_HOURS = 24
BURST_THRESHOLD = 2  # prior requests for the same customer within the window

HIGH_VALUE = "high_value"
REPEAT_CUSTOMER = "repeat_customer"
RAPID_SUCCESSION = "rapid_succession"
FRAUD_DISPUTE = "fraud_dispute"

FLAG_LABELS = {
    HIGH_VALUE: "High value",
    REPEAT_CUSTOMER: "Repeat refunds",
    RAPID_SUCCESSION: "Rapid succession",
    FRAUD_DISPUTE: "Fraud dispute",
}


def compute_flags(
    session: Session,
    *,
    customer_id: str,
    amount_cents: int,
    reason: Reason,
    at: datetime,
) -> list[str]:
    flags: list[str] = []
    if amount_cents > HIGH_VALUE_CENTS:
        flags.append(HIGH_VALUE)

    prior_approved = session.scalar(
        select(func.count())
        .select_from(RefundRequest)
        .where(
            RefundRequest.customer_id == customer_id,
            RefundRequest.status == Status.approved,
            RefundRequest.created_at >= at - timedelta(days=REPEAT_WINDOW_DAYS),
        )
    )
    if (prior_approved or 0) >= REPEAT_THRESHOLD:
        flags.append(REPEAT_CUSTOMER)

    recent = session.scalar(
        select(func.count())
        .select_from(RefundRequest)
        .where(
            RefundRequest.customer_id == customer_id,
            RefundRequest.created_at >= at - timedelta(hours=BURST_WINDOW_HOURS),
        )
    )
    if (recent or 0) >= BURST_THRESHOLD:
        flags.append(RAPID_SUCCESSION)

    if reason is Reason.fraud_dispute:
        flags.append(FRAUD_DISPUTE)

    return flags


def requires_admin(flags: list[str]) -> bool:
    """High value on its own is manager-confirmable; high value plus any other
    signal escalates to an admin."""
    return HIGH_VALUE in flags and len(flags) > 1


def requires_confirmation(flags: list[str]) -> bool:
    return bool(flags)
