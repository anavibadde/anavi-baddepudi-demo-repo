"""Populate the demo database with a fake org chart and customer refund requests."""

from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy.orm import Session

from .auth import hash_password
from .db import SessionLocal, create_all, engine
from .entitlements import grant
from .flags.models import (
    ChangeStatus,
    Environment,
    FeatureFlag,
    FlagAction,
    FlagChangeRequest,
    FlagEvent,
    FlagState,
)
from .models import AppRole, AppSlug, Base, Role, User, utcnow
from .refunds.models import Action, DecisionEvent, Reason, RefundRequest, Status
from .refunds.risk import compute_flags

# Everyone shares one password: a fake org of thirteen is not worth thirteen
# secrets, and the README has to print it anyway.
DEMO_PASSWORD = "refunds123"

ORG = [
    ("Priya Raman", "priya@example.com", Role.admin, None),
    ("Marco Silva", "marco@example.com", Role.manager, "priya@example.com"),
    ("Dana Okafor", "dana@example.com", Role.manager, "priya@example.com"),
    ("Ines Roth", "ines@example.com", Role.manager, "priya@example.com"),
    ("Anya Patel", "anya@example.com", Role.analyst, "marco@example.com"),
    ("Tom Becker", "tom@example.com", Role.analyst, "marco@example.com"),
    ("Leo Nakamura", "leo@example.com", Role.analyst, "marco@example.com"),
    ("Sam Whitfield", "sam@example.com", Role.analyst, "dana@example.com"),
    ("Rita Alvarez", "rita@example.com", Role.analyst, "dana@example.com"),
    ("Jonas Berg", "jonas@example.com", Role.analyst, "dana@example.com"),
    ("Mia Chen", "mia@example.com", Role.analyst, "ines@example.com"),
    ("Omar Haddad", "omar@example.com", Role.analyst, "ines@example.com"),
    ("Fern Doyle", "fern@example.com", Role.analyst, None),  # no manager: admin-only queue
]

# Grants are per tool, so the home page differs by person rather than showing
# everyone everything. Platform admins hold every tool implicitly.
REFUND_ROLES = {
    Role.manager: AppRole.reviewer,
    Role.analyst: AppRole.contributor,
}

# Flags is a narrower tool than refunds: most analysts hold nothing, so the
# home page visibly differs per person. Ines proposes, Marco and Dana approve —
# maker-checker needs at least two approvers who are not the proposer.
FLAG_ROLES = {
    "marco@example.com": AppRole.reviewer,
    "dana@example.com": AppRole.reviewer,
    "ines@example.com": AppRole.contributor,
    "leo@example.com": AppRole.viewer,
}

# dev value, prod value
FLAGS = [
    (
        "checkout.express_refunds",
        "Express refunds at checkout",
        "Offers an instant refund path instead of the review queue.",
        True,
        False,
    ),
    (
        "support.chat_widget",
        "Support chat widget",
        "Shows the live chat launcher on customer-facing pages.",
        True,
        True,
    ),
    (
        "pricing.annual_discount",
        "Annual plan discount",
        "Advertises the 20% annual discount on the pricing page.",
        True,
        False,
    ),
    (
        "dashboard.new_nav",
        "Redesigned navigation",
        "Replaces the sidebar with the new top navigation.",
        False,
        False,
    ),
]

CUSTOMERS = [
    ("CUS-1041", "Elena Fischer"),
    ("CUS-1088", "Raj Mehta"),
    ("CUS-1123", "Grace Liu"),
    ("CUS-1190", "Peter Novak"),
    ("CUS-1204", "Aisha Bello"),
    ("CUS-1251", "Hugo Martins"),
    ("CUS-1299", "Yuki Tanaka"),
    ("CUS-1310", "Claire Dubois"),
    ("CUS-1355", "Noah Klein"),
    ("CUS-1402", "Sofia Rossi"),
]

NOTES = {
    Reason.duplicate_charge: "Customer charged twice for the same order; second capture confirmed.",
    Reason.incorrect_amount: "Charged the pre-discount price; difference owed back.",
    Reason.item_not_received: "Carrier shows delivered, customer disputes; no signature on file.",
    Reason.item_damaged: "Photos attached, item arrived cracked.",
    Reason.cancelled_order: "Cancelled within the window but the capture went through.",
    Reason.fraud_dispute: "Customer reports they did not authorise this transaction.",
    Reason.other: "Goodwill gesture after a support escalation.",
}

APPROVE_COMMENTS = [
    "Duplicate confirmed in the payment log.",
    "Matches the order total, approving.",
    "Support thread checks out.",
]
REJECT_COMMENTS = [
    "Outside the 30-day refund window.",
    "Delivery confirmed with signature; send to disputes instead.",
    "Amount does not match the order; ask the customer for the receipt.",
]


def reset() -> None:
    Base.metadata.drop_all(engine)
    create_all()


def seed(session: Session, *, count: int = 54, rng: random.Random | None = None) -> None:
    rng = rng or random.Random(11)
    by_email: dict[str, User] = {}
    # Hash once: pbkdf2 thirteen times over is a slow seed for no benefit.
    password_hash = hash_password(DEMO_PASSWORD)
    for name, email, role, _ in ORG:
        user = User(name=name, email=email, role=role, password_hash=password_hash)
        session.add(user)
        by_email[email] = user
    session.flush()
    for _, email, _, manager_email in ORG:
        if manager_email:
            by_email[email].manager_id = by_email[manager_email].id
    session.flush()

    for user in by_email.values():
        app_role = REFUND_ROLES.get(user.role)
        if app_role is not None:
            grant(session, user, AppSlug.refunds, app_role)
        flag_role = FLAG_ROLES.get(user.email)
        if flag_role is not None:
            grant(session, user, AppSlug.flags, flag_role)
    session.flush()

    seed_flags(session, by_email)

    submitters = [u for u in by_email.values() if u.role is not Role.admin]
    now = utcnow()

    for i in range(count):
        submitter = rng.choice(submitters)
        reason = rng.choice(list(Reason))
        # A deliberate minority land above the $1,000 high-value threshold, and a
        # few customers repeat so the risk heuristics have something to find.
        amount = (
            rng.randrange(100_500, 420_000) if rng.random() < 0.22 else rng.randrange(1_200, 96_000)
        )
        pool = CUSTOMERS[:4] if rng.random() < 0.4 else CUSTOMERS
        customer_id, customer_name = rng.choice(pool)
        created_at = now - timedelta(days=rng.randrange(0, 40), hours=rng.randrange(0, 24))
        flags = compute_flags(
            session,
            customer_id=customer_id,
            amount_cents=amount,
            reason=reason,
            at=created_at,
        )
        request = RefundRequest(
            customer_id=customer_id,
            customer_name=customer_name,
            order_id=f"ORD-{rng.randrange(40000, 99999)}",
            reason=reason,
            amount_cents=amount,
            note=NOTES[reason],
            risk_flags=flags,
            created_by=submitter.id,
            created_at=created_at,
        )
        session.add(request)
        session.flush()
        session.add(
            DecisionEvent(
                request_id=request.id,
                actor_id=submitter.id,
                action=Action.submitted,
                comment=request.note,
                created_at=created_at,
            )
        )

        roll = rng.random()
        if roll < 0.45 or i < 6:  # keep a healthy pending queue
            continue
        reviewer_id = submitter.manager_id or by_email["priya@example.com"].id
        decided_at = created_at + timedelta(hours=rng.randrange(2, 72))
        approved = roll < 0.8
        request.status = Status.approved if approved else Status.rejected
        request.decided_by = reviewer_id
        request.decided_at = decided_at
        session.add(
            DecisionEvent(
                request_id=request.id,
                actor_id=reviewer_id,
                action=Action.approved if approved else Action.rejected,
                comment=rng.choice(APPROVE_COMMENTS if approved else REJECT_COMMENTS),
                created_at=decided_at,
            )
        )
        session.flush()

    session.commit()


def seed_flags(session: Session, by_email: dict[str, User]) -> None:
    now = utcnow()
    ines = by_email["ines@example.com"]
    marco = by_email["marco@example.com"]
    flags: dict[str, FeatureFlag] = {}
    for key, name, description, dev, prod in FLAGS:
        flag = FeatureFlag(key=key, name=name, description=description, created_at=now)
        session.add(flag)
        session.flush()
        flags[key] = flag
        for environment, enabled in ((Environment.dev, dev), (Environment.prod, prod)):
            session.add(
                FlagState(
                    flag_id=flag.id,
                    environment=environment,
                    enabled=enabled,
                    updated_at=now - timedelta(days=3),
                    updated_by=ines.id,
                )
            )
            session.add(
                FlagEvent(
                    flag_id=flag.id,
                    environment=environment,
                    action=FlagAction.set_directly,
                    from_value=False,
                    to_value=enabled,
                    comment="Initial state.",
                    actor_id=ines.id,
                    created_at=now - timedelta(days=3),
                )
            )

    # One prod change waiting on someone other than Ines, so the demo opens on
    # a queue with something in it.
    express = flags["checkout.express_refunds"]
    request = FlagChangeRequest(
        flag_id=express.id,
        environment=Environment.prod,
        from_value=False,
        to_value=True,
        reason="Soaked in dev for two weeks with no refund-queue regressions.",
        status=ChangeStatus.pending,
        requested_by=ines.id,
        requested_at=now - timedelta(hours=20),
    )
    session.add(request)
    session.flush()
    session.add(
        FlagEvent(
            flag_id=express.id,
            environment=Environment.prod,
            action=FlagAction.proposed,
            from_value=False,
            to_value=True,
            comment=request.reason,
            actor_id=ines.id,
            request_id=request.id,
            created_at=request.requested_at,
        )
    )

    # A closed one so the history is not empty on first load.
    chat = flags["support.chat_widget"]
    done = FlagChangeRequest(
        flag_id=chat.id,
        environment=Environment.prod,
        from_value=False,
        to_value=True,
        reason="Support wants the launcher on for the holiday period.",
        status=ChangeStatus.applied,
        requested_by=ines.id,
        requested_at=now - timedelta(days=2),
        decided_by=marco.id,
        decided_at=now - timedelta(days=2, hours=-3),
        decision_note="Checked with support on staffing.",
    )
    session.add(done)
    session.flush()
    session.add(
        FlagEvent(
            flag_id=chat.id,
            environment=Environment.prod,
            action=FlagAction.applied,
            from_value=False,
            to_value=True,
            comment=done.decision_note,
            actor_id=marco.id,
            request_id=done.id,
            created_at=done.decided_at,
        )
    )
    session.flush()


def main() -> None:
    reset()
    with SessionLocal() as session:
        seed(session)
        print("Seeded demo database.")
        print(f"Sign in with any user id below and the password {DEMO_PASSWORD!r}:")
        for user in session.query(User).order_by(User.id):
            print(f"  {user.id:>2}  {user.name} ({user.role.value})")


if __name__ == "__main__":
    main()
