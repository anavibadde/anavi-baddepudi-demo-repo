from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session, selectinload

from .aging import AGING_LABELS, DUE_HOURS, OVERDUE_HOURS, age_hours, aging_tier
from .auth import (
    authenticate,
    issue_token,
    revoke_token,
    revoke_user_sessions,
    user_for_token,
)
from .db import create_all, get_session
from .models import Action, DecisionEvent, Reason, RefundRequest, Role, Status, User, utcnow
from .risk import FLAG_LABELS, HIGH_VALUE_CENTS, compute_flags, requires_admin
from .rules import DecisionDenied, can_view, check_can_decide, reviewer_for, visible_requests
from .schemas import (
    DecisionIn,
    EventOut,
    LoginIn,
    LoginOut,
    RequestCreate,
    RequestDetailOut,
    RequestPage,
    SwitchIn,
    UserOut,
    UserUpdate,
)

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200

# Impersonation without a password is a backdoor, so it is a deployment choice
# rather than a code path that always exists. On here so the demo can be walked
# through from one screen; set DEMO_SWITCH=0 and the endpoint 404s.
DEMO_SWITCH = os.getenv("DEMO_SWITCH", "1").lower() not in {"0", "false", "no"}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_all()
    yield


app = FastAPI(title="Refund Review (demo)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def bearer_token(authorization: str = Header(default="")) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return token


def current_user(
    token: str = Depends(bearer_token),
    session: Session = Depends(get_session),
) -> User:
    user = user_for_token(session, token)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_session")
    return user


def _decision_availability(viewer: User, request: RefundRequest) -> tuple[bool, str | None]:
    """Whether the viewer could decide this request, ignoring the risk tick-box
    (the UI collects that separately)."""
    try:
        check_can_decide(
            viewer, request, request.submitter, action=Action.approved, confirmed_risk=True
        )
    except DecisionDenied as denied:
        return False, denied.reason
    return True, None


def _serialize(viewer: User, request: RefundRequest) -> dict:
    can_decide, blocked_reason = _decision_availability(viewer, request)
    flags = list(request.risk_flags or [])
    pending = request.status is Status.pending
    # No active reviewer in the submitter's line means this only moves if an
    # admin picks it up — worth saying out loud rather than leaving it to rot.
    unassigned = pending and reviewer_for(request.submitter) is None
    return {
        "id": request.id,
        "customer_id": request.customer_id,
        "customer_name": request.customer_name,
        "order_id": request.order_id,
        "reason": request.reason,
        "amount_cents": request.amount_cents,
        "currency": request.currency,
        "note": request.note,
        "status": request.status,
        "risk_flags": flags,
        "requires_admin": requires_admin(flags),
        "created_at": request.created_at,
        "decided_at": request.decided_at,
        "submitter": UserOut.model_validate(request.submitter),
        "decider": UserOut.model_validate(request.decider) if request.decider else None,
        "can_decide": can_decide,
        "decide_blocked_reason": blocked_reason,
        "age_hours": round(age_hours(request.created_at), 1),
        "aging": aging_tier(request.created_at, pending=pending),
        "unassigned": unassigned,
    }


def _serialize_detail(viewer: User, request: RefundRequest) -> dict:
    data = _serialize(viewer, request)
    data["events"] = [
        EventOut(
            id=e.id,
            action=e.action,
            comment=e.comment,
            created_at=e.created_at,
            actor=UserOut.model_validate(e.actor),
        )
        for e in request.events
    ]
    return data


def _load_visible(request_id: int, viewer: User, session: Session) -> RefundRequest:
    request = session.get(RefundRequest, request_id)
    if request is None or not can_view(viewer, request, request.submitter):
        # 404 rather than 403 so request IDs outside the viewer's line cannot be probed.
        raise HTTPException(status_code=404, detail="not_found")
    return request


@app.post("/api/auth/login", response_model=LoginOut)
def login(payload: LoginIn, session: Session = Depends(get_session)) -> dict:
    user = authenticate(session, user_id=payload.user_id, password=payload.password)
    if user is None:
        # One message for both wrong id and wrong password: saying which is wrong
        # tells an outsider which ids exist.
        raise HTTPException(status_code=401, detail="invalid_credentials")
    record = issue_token(session, user)
    return {"token": record.token, "expires_at": record.expires_at, "user": user}


@app.post("/api/auth/logout", status_code=204, response_model=None)
def logout(token: str = Depends(bearer_token), session: Session = Depends(get_session)) -> Response:
    revoke_token(session, token)
    return Response(status_code=204)


@app.post("/api/auth/switch", response_model=LoginOut)
def switch_user(
    payload: SwitchIn,
    token: str = Depends(bearer_token),
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Demo only: become another seeded user without their password.

    The new identity is a real session, so every visibility and decision check
    downstream runs against the person you switched to — this hands out a
    different token, it does not let the browser claim a role.
    """
    if not DEMO_SWITCH:
        raise HTTPException(status_code=404, detail="not_found")
    target = session.get(User, payload.user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="not_found")
    if not target.is_active:
        raise HTTPException(status_code=400, detail="account_deactivated")
    # Drop the old session rather than leaving a trail of live tokens behind.
    revoke_token(session, token)
    record = issue_token(session, target)
    return {"token": record.token, "expires_at": record.expires_at, "user": target}


@app.get("/api/auth/me", response_model=UserOut)
def me(viewer: User = Depends(current_user)) -> User:
    return viewer


@app.get("/api/config")
def get_config() -> dict:
    return {
        "high_value_cents": HIGH_VALUE_CENTS,
        "reasons": [r.value for r in Reason],
        "flag_labels": FLAG_LABELS,
        "aging_labels": AGING_LABELS,
        "due_hours": DUE_HOURS,
        "overdue_hours": OVERDUE_HOURS,
        "page_size": DEFAULT_PAGE_SIZE,
        "demo_switch": DEMO_SWITCH,
        "demo_notice": "Demo only — no refunds are executed and no money moves.",
    }


@app.get("/api/users", response_model=list[UserOut])
def list_users(
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[User]:
    return list(session.scalars(select(User).order_by(User.role, User.name)))


@app.patch("/api/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    viewer: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> User:
    """Change someone's role, manager or active state. Any of those changes what
    they are allowed to see, so their live sessions go with it."""
    if viewer.role is not Role.admin:
        raise HTTPException(status_code=403, detail="admin_only")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="not_found")
    if payload.manager_id == user.id:
        raise HTTPException(status_code=400, detail="cannot_report_to_self")
    if payload.manager_id is not None and session.get(User, payload.manager_id) is None:
        raise HTTPException(status_code=404, detail="manager_not_found")

    # model_fields_set, not None-checks: clearing a manager is a real change.
    changed = payload.model_fields_set
    if payload.role is not None:
        user.role = payload.role
    if "manager_id" in changed:
        user.manager_id = payload.manager_id
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if changed:
        revoke_user_sessions(session, user.id)
    session.commit()
    session.refresh(user)
    return user


@app.get("/api/requests", response_model=RequestPage)
def list_requests(
    status: Status | None = Query(default=None),
    flagged: bool | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    viewer: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    stmt = visible_requests(viewer)
    if status is not None:
        stmt = stmt.where(RefundRequest.status == status)
    if flagged is not None:
        has_flags = func.json_array_length(RefundRequest.risk_flags) > 0
        stmt = stmt.where(has_flags if flagged else ~has_flags)

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    # Pending first, then riskiest, then oldest: the queue is a work list, and
    # ordering by age means anything breaching its SLA rises instead of being
    # buried under newer submissions. Paging happens after this, in SQL, so
    # page two is the rest of the same list rather than a different sort.
    page = (
        stmt.options(
            selectinload(RefundRequest.submitter),
            selectinload(RefundRequest.decider),
            selectinload(RefundRequest.submitter, User.manager),
        )
        .order_by(
            case((RefundRequest.status == Status.pending, 0), else_=1),
            func.json_array_length(RefundRequest.risk_flags).desc(),
            RefundRequest.created_at.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [_serialize(viewer, r) for r in session.scalars(page)],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/requests", response_model=RequestDetailOut, status_code=201)
def create_request(
    payload: RequestCreate,
    viewer: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    if payload.idempotency_key:
        existing = session.scalar(
            select(RefundRequest).where(
                RefundRequest.idempotency_key == payload.idempotency_key,
                RefundRequest.created_by == viewer.id,
            )
        )
        if existing is not None:
            return _serialize_detail(viewer, existing)

    created_at = utcnow()
    flags = compute_flags(
        session,
        customer_id=payload.customer_id,
        amount_cents=payload.amount_cents,
        reason=payload.reason,
        at=created_at,
    )
    request = RefundRequest(
        customer_id=payload.customer_id,
        customer_name=payload.customer_name,
        order_id=payload.order_id,
        reason=payload.reason,
        amount_cents=payload.amount_cents,
        note=payload.note,
        risk_flags=flags,
        created_by=viewer.id,
        created_at=created_at,
        idempotency_key=payload.idempotency_key,
    )
    session.add(request)
    session.flush()
    session.add(
        DecisionEvent(
            request_id=request.id,
            actor_id=viewer.id,
            action=Action.submitted,
            comment=payload.note,
            created_at=created_at,
        )
    )
    session.commit()
    session.refresh(request)
    return _serialize_detail(viewer, request)


@app.get("/api/requests/{request_id}", response_model=RequestDetailOut)
def get_request(
    request_id: int,
    viewer: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    return _serialize_detail(viewer, _load_visible(request_id, viewer, session))


@app.post("/api/requests/{request_id}/decision", response_model=RequestDetailOut)
def decide(
    request_id: int,
    payload: DecisionIn,
    viewer: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    if payload.action is Action.submitted:
        raise HTTPException(status_code=400, detail="invalid_action")
    request = _load_visible(request_id, viewer, session)
    if payload.action is Action.rejected and not payload.comment.strip():
        raise HTTPException(status_code=400, detail="rejection_comment_required")

    try:
        check_can_decide(
            viewer,
            request,
            request.submitter,
            action=payload.action,
            confirmed_risk=payload.confirm_risk,
        )
    except DecisionDenied as denied:
        raise HTTPException(status_code=denied.status_code, detail=denied.reason) from denied

    decided_at = datetime.now(timezone.utc)
    status = Status.approved if payload.action is Action.approved else Status.rejected
    # Conditional on still being pending: two reviewers clicking at once means the
    # second one loses here rather than overwriting the first decision.
    result = session.execute(
        update(RefundRequest)
        .where(RefundRequest.id == request.id, RefundRequest.status == Status.pending)
        .values(status=status, decided_by=viewer.id, decided_at=decided_at)
    )
    if result.rowcount == 0:
        session.rollback()
        raise HTTPException(status_code=409, detail="already_decided")

    session.add(
        DecisionEvent(
            request_id=request.id,
            actor_id=viewer.id,
            action=payload.action,
            comment=payload.comment.strip(),
        )
    )
    session.commit()
    session.expire_all()
    return _serialize_detail(viewer, session.get(RefundRequest, request_id))
