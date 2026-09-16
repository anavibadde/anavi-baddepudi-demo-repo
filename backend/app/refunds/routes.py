from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session, selectinload

from ..db import get_session
from ..deps import require_app
from ..models import AppRole, AppSlug, User
from ..schemas import UserOut
from .aging import AGING_LABELS, DUE_HOURS, OVERDUE_HOURS, age_hours, aging_tier
from .models import Action, DecisionEvent, Reason, RefundRequest, Status, utcnow
from .risk import FLAG_LABELS, HIGH_VALUE_CENTS, compute_flags, requires_admin
from .rules import DecisionDenied, can_view, check_can_decide, reviewer_for, visible_requests
from .schemas import (
    DecisionIn,
    EventOut,
    RequestCreate,
    RequestDetailOut,
    RequestPage,
)

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200

router = APIRouter(prefix="/api/refunds", tags=["refunds"])

# Holding the tool is the door; who may decide what inside it is still the
# hierarchy rule in rules.py, which this does not replace.
refunds_user = require_app(AppSlug.refunds, AppRole.viewer)
refunds_contributor = require_app(AppSlug.refunds, AppRole.contributor)


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


@router.get("/config")
def get_config(_: User = Depends(refunds_user)) -> dict:
    return {
        "high_value_cents": HIGH_VALUE_CENTS,
        "reasons": [r.value for r in Reason],
        "flag_labels": FLAG_LABELS,
        "aging_labels": AGING_LABELS,
        "due_hours": DUE_HOURS,
        "overdue_hours": OVERDUE_HOURS,
        "page_size": DEFAULT_PAGE_SIZE,
    }


@router.get("/requests", response_model=RequestPage)
def list_requests(
    status: Status | None = Query(default=None),
    flagged: bool | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    viewer: User = Depends(refunds_user),
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


@router.post("/requests", response_model=RequestDetailOut, status_code=201)
def create_request(
    payload: RequestCreate,
    viewer: User = Depends(refunds_contributor),
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


@router.get("/requests/{request_id}", response_model=RequestDetailOut)
def get_request(
    request_id: int,
    viewer: User = Depends(refunds_user),
    session: Session = Depends(get_session),
) -> dict:
    return _serialize_detail(viewer, _load_visible(request_id, viewer, session))


@router.post("/requests/{request_id}/decision", response_model=RequestDetailOut)
def decide(
    request_id: int,
    payload: DecisionIn,
    viewer: User = Depends(refunds_user),
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
