"""How long a request has been waiting, and when that becomes a problem.

Aging applies to pending requests only: once something is decided, how long it
sat is history rather than work.
"""

from __future__ import annotations

from datetime import datetime, timezone

DUE_HOURS = 72
OVERDUE_HOURS = 168

AGING_LABELS = {
    "due": f"Waiting over {DUE_HOURS // 24} days",
    "overdue": f"Waiting over {OVERDUE_HOURS // 24} days",
}


def age_hours(created_at: datetime, *, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    # SQLite hands back naive datetimes; everything stored is UTC.
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (now - created_at).total_seconds() / 3600


def aging_tier(created_at: datetime, *, pending: bool, now: datetime | None = None) -> str | None:
    if not pending:
        return None
    hours = age_hours(created_at, now=now)
    if hours >= OVERDUE_HOURS:
        return "overdue"
    if hours >= DUE_HOURS:
        return "due"
    return None
