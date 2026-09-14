from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from .db import create_all, get_session
from .models import Action, DecisionEvent, Reason, RefundRequest, Status, User, utcnow
from .risk import FLAG_LABELS, HIGH_VALUE_CENTS, compute_flags, requires_admin
from .rules import DecisionDenied, can_view, check_can_decide, visible_requests
from .schemas import (
    DecisionIn,
    EventOut,
    RequestCreate,
    RequestDetailOut,
    RequestOut,
    UserOut,
)


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


def current_user(
    x_user_id: int = Header(..., alias="X-User-Id"),
    session: Session = Depends(get_session),
) -> User:
    """Demo authentication: the client asserts who it is. Never do this for real."""
    user = session.get(User, x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="unknown_user")
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


@app.get("/api/config")
def get_config() -> dict:
    return {
        "high_value_cents": HIGH_VALUE_CENTS,
        "reasons": [r.value for r in Reason],
        "flag_labels": FLAG_LABELS,
        "demo_notice": "Demo only — no refunds are executed and no money moves.",
    }


@app.get("/api/users", response_model=list[UserOut])
def list_users(session: Session = Depends(get_session)) -> list[User]:
    return list(session.scalars(select(User).order_by(User.role, User.name)))


@app.get("/api/requests", response_model=list[RequestOut])
def list_requests(
    status: Status | None = Query(default=None),
    flagged: bool | None = Query(default=None),
    viewer: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[dict]:
    stmt = visible_requests(viewer).options(
        selectinload(RefundRequest.submitter), selectinload(RefundRequest.decider)
    )
    if status is not None:
        stmt = stmt.where(RefundRequest.status == status)
    stmt = stmt.order_by(RefundRequest.created_at.desc())
    rows = [_serialize(viewer, r) for r in session.scalars(stmt)]
    if flagged is not None:
        rows = [r for r in rows if bool(r["risk_flags"]) is flagged]
    # Pending first, then riskiest, then newest: the queue is a work list.
    rows.sort(
        key=lambda r: (
            r["status"] is not Status.pending,
            -len(r["risk_flags"]),
            -r["amount_cents"],
        )
    )
    return rows


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
