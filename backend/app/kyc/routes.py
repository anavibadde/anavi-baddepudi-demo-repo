from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import require_app
from ..entitlements import effective_role, holds
from ..models import AppRole, AppSlug, User
from ..schemas import UserOut
from .models import (
    CLAIM_TTL,
    TERMINAL,
    CaseAction,
    CaseStatus,
    KycCase,
    KycEvent,
    RiskTier,
    utcnow,
)
from .rules import (
    CLAIMABLE,
    KycDenied,
    check_can_claim,
    check_can_recommend,
    check_can_release,
    check_can_sign_off,
    claim_expired,
)
from .schemas import (
    CaseDetailOut,
    CaseOut,
    EventOut,
    InfoSuppliedIn,
    NeedsInfoIn,
    RecommendIn,
    SignOffIn,
)

router = APIRouter(prefix="/api/kyc", tags=["kyc"])

kyc_user = require_app(AppSlug.kyc, AppRole.viewer)
kyc_reviewer = require_app(AppSlug.kyc, AppRole.contributor)
kyc_approver = require_app(AppSlug.kyc, AppRole.reviewer)

OUTCOMES = (CaseStatus.approved, CaseStatus.rejected)


def _denied(denied: KycDenied) -> HTTPException:
    return HTTPException(status_code=denied.status_code, detail=denied.reason)


def _case(session: Session, case_id: int) -> KycCase:
    case = session.get(KycCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="not_found")
    return case


def _log(
    session: Session,
    case: KycCase,
    action: CaseAction,
    actor: User | None,
    comment: str = "",
) -> None:
    session.add(
        KycEvent(
            case_id=case.id,
            action=action,
            cycle=case.cycles,
            comment=comment,
            actor_id=actor.id if actor else None,
        )
    )


def _permissions(
    viewer: User, case: KycCase, role: AppRole | None
) -> tuple[bool, bool, bool, str | None]:
    blocked: str | None = None
    checks = (
        (check_can_claim, holds(role, AppRole.contributor)),
        (check_can_recommend, holds(role, AppRole.contributor)),
        (check_can_sign_off, holds(role, AppRole.reviewer)),
    )
    allowed: list[bool] = []
    for check, permitted in checks:
        if not permitted:
            allowed.append(False)
            continue
        try:
            check(viewer, case)
            allowed.append(True)
        except KycDenied as denied:
            allowed.append(False)
            # The sign-off reason is the interesting one: it is what tells a
            # reviewer they recommended this case themselves.
            if check is check_can_sign_off and case.status is CaseStatus.recommended:
                blocked = denied.reason
    return allowed[0], allowed[1], allowed[2], blocked


def _serialize(viewer: User, case: KycCase, role: AppRole | None) -> dict:
    can_claim, can_recommend, can_sign_off, blocked = _permissions(viewer, case, role)
    return {
        "id": case.id,
        "reference": case.reference,
        "applicant_name": case.applicant_name,
        "country": case.country,
        "entity_type": case.entity_type,
        "risk_tier": case.risk_tier,
        "summary": case.summary,
        "status": case.status,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "cycles": case.cycles,
        "claimer": UserOut.model_validate(case.claimer) if case.claimer else None,
        "claimed_at": case.claimed_at,
        "claim_expires_at": case.claim_expires_at,
        "claim_expired": claim_expired(case),
        "recommender": UserOut.model_validate(case.recommender) if case.recommender else None,
        "recommendation": case.recommendation,
        "recommended_at": case.recommended_at,
        "decider": UserOut.model_validate(case.decider) if case.decider else None,
        "decided_at": case.decided_at,
        "can_claim": can_claim,
        "can_recommend": can_recommend,
        "can_sign_off": can_sign_off,
        "blocked_reason": blocked,
    }


@router.get("/config")
def get_config(
    viewer: User = Depends(kyc_user),
    session: Session = Depends(get_session),
) -> dict:
    role = effective_role(session, viewer, AppSlug.kyc)
    return {
        "statuses": [status.value for status in CaseStatus],
        "risk_tiers": [tier.value for tier in RiskTier],
        "claim_hours": int(CLAIM_TTL.total_seconds() // 3600),
        "can_review": holds(role, AppRole.contributor),
        "can_sign_off": holds(role, AppRole.reviewer),
    }


@router.get("/cases", response_model=list[CaseOut])
def list_cases(
    status: CaseStatus | None = None,
    mine: bool = False,
    viewer: User = Depends(kyc_user),
    session: Session = Depends(get_session),
) -> list[dict]:
    """One shared pool. Unlike refunds there is no org-chart filter here —
    everyone holding the tool works the same queue."""
    query = select(KycCase)
    if status is not None:
        query = query.where(KycCase.status == status)
    if mine:
        query = query.where(KycCase.claimed_by == viewer.id)
    cases = session.scalars(query.order_by(KycCase.created_at))
    role = effective_role(session, viewer, AppSlug.kyc)
    return [_serialize(viewer, case, role) for case in cases]


@router.get("/cases/{case_id}", response_model=CaseDetailOut)
def get_case(
    case_id: int,
    viewer: User = Depends(kyc_user),
    session: Session = Depends(get_session),
) -> dict:
    case = _case(session, case_id)
    role = effective_role(session, viewer, AppSlug.kyc)
    data = _serialize(viewer, case, role)
    events = session.scalars(
        select(KycEvent).where(KycEvent.case_id == case.id).order_by(KycEvent.id.desc())
    )
    data["events"] = [
        EventOut(
            id=event.id,
            action=event.action,
            cycle=event.cycle,
            comment=event.comment,
            actor=UserOut.model_validate(event.actor) if event.actor else None,
            created_at=event.created_at,
        )
        for event in events
    ]
    return data


@router.post("/cases/{case_id}/claim", response_model=CaseDetailOut)
def claim(
    case_id: int,
    viewer: User = Depends(kyc_reviewer),
    session: Session = Depends(get_session),
) -> dict:
    case = _case(session, case_id)
    try:
        check_can_claim(viewer, case)
    except KycDenied as denied:
        raise _denied(denied) from denied

    now = utcnow()
    lapsed_holder = case.claimed_by
    # Conditional on the claim still being free or lapsed: two people hitting
    # claim at once means the second is told, not silently given the case.
    taken = session.execute(
        update(KycCase)
        .where(
            KycCase.id == case.id,
            KycCase.status.in_(CLAIMABLE),
            or_(KycCase.claimed_by.is_(None), KycCase.claim_expires_at <= now),
        )
        .values(
            claimed_by=viewer.id,
            claimed_at=now,
            claim_expires_at=now + CLAIM_TTL,
            status=CaseStatus.claimed,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if taken.rowcount == 0:
        session.rollback()
        raise HTTPException(status_code=409, detail="claimed_by_someone_else")

    if lapsed_holder is not None:
        _log(session, case, CaseAction.claim_expired, None)
    _log(session, case, CaseAction.claimed, viewer)
    session.commit()
    session.expire_all()
    return get_case(case_id, viewer, session)


@router.post("/cases/{case_id}/release", response_model=CaseDetailOut)
def release(
    case_id: int,
    viewer: User = Depends(kyc_reviewer),
    session: Session = Depends(get_session),
) -> dict:
    case = _case(session, case_id)
    try:
        check_can_release(viewer, case)
    except KycDenied as denied:
        raise _denied(denied) from denied

    case.claimed_by = None
    case.claimed_at = None
    case.claim_expires_at = None
    case.updated_at = utcnow()
    if case.status is CaseStatus.claimed:
        case.status = CaseStatus.new
    _log(session, case, CaseAction.released, viewer)
    session.commit()
    session.expire_all()
    return get_case(case_id, viewer, session)


@router.post("/cases/{case_id}/recommendation", response_model=CaseDetailOut)
def recommend(
    case_id: int,
    payload: RecommendIn,
    viewer: User = Depends(kyc_reviewer),
    session: Session = Depends(get_session),
) -> dict:
    """The maker half: a recommendation, not a decision. Nothing is final
    until a different reviewer signs it off."""
    case = _case(session, case_id)
    if payload.recommendation not in OUTCOMES:
        raise HTTPException(status_code=400, detail="invalid_recommendation")
    try:
        check_can_recommend(viewer, case)
    except KycDenied as denied:
        raise _denied(denied) from denied

    now = utcnow()
    case.status = CaseStatus.recommended
    case.recommendation = payload.recommendation
    case.recommended_by = viewer.id
    case.recommended_at = now
    case.updated_at = now
    _log(
        session,
        case,
        CaseAction.recommended,
        viewer,
        comment=payload.note.strip() or payload.recommendation.value,
    )
    session.commit()
    session.expire_all()
    return get_case(case_id, viewer, session)


@router.post("/cases/{case_id}/sign-off", response_model=CaseDetailOut)
def sign_off(
    case_id: int,
    payload: SignOffIn,
    viewer: User = Depends(kyc_approver),
    session: Session = Depends(get_session),
) -> dict:
    """The checker half. Approving applies the recommendation that was made,
    not an outcome the signer picks: agreeing and deciding are the same act."""
    case = _case(session, case_id)
    try:
        check_can_sign_off(viewer, case)
    except KycDenied as denied:
        raise _denied(denied) from denied
    if case.recommendation not in OUTCOMES:
        raise HTTPException(status_code=409, detail="no_recommendation")

    now = utcnow()
    if payload.approve:
        outcome = case.recommendation
        closed = session.execute(
            update(KycCase)
            .where(KycCase.id == case.id, KycCase.status == CaseStatus.recommended)
            .values(
                status=outcome,
                decided_by=viewer.id,
                decided_at=now,
                updated_at=now,
                claimed_by=None,
                claimed_at=None,
                claim_expires_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        if closed.rowcount == 0:
            session.rollback()
            raise HTTPException(status_code=409, detail="already_decided")
        action = CaseAction.approved if outcome is CaseStatus.approved else CaseAction.rejected
        _log(session, case, action, viewer, comment=payload.note.strip())
    else:
        # Disagreeing returns the case to the pool for a fresh review rather
        # than letting the checker impose the opposite outcome alone.
        case.status = CaseStatus.new
        case.recommendation = None
        case.recommended_by = None
        case.recommended_at = None
        case.claimed_by = None
        case.claimed_at = None
        case.claim_expires_at = None
        case.cycles += 1
        case.updated_at = now
        _log(session, case, CaseAction.released, viewer, comment=payload.note.strip())

    session.commit()
    session.expire_all()
    return get_case(case_id, viewer, session)


@router.post("/cases/{case_id}/needs-info", response_model=CaseDetailOut)
def needs_info(
    case_id: int,
    payload: NeedsInfoIn,
    viewer: User = Depends(kyc_approver),
    session: Session = Depends(get_session),
) -> dict:
    """The third outcome refunds do not have: the case reopens instead of
    ending, and its history carries across the cycle."""
    case = _case(session, case_id)
    if case.status in TERMINAL:
        raise HTTPException(status_code=409, detail="already_decided")
    if case.status is not CaseStatus.recommended:
        raise HTTPException(status_code=409, detail="no_recommendation")

    now = utcnow()
    case.status = CaseStatus.needs_info
    case.recommendation = None
    case.recommended_by = None
    case.recommended_at = None
    case.claimed_by = None
    case.claimed_at = None
    case.claim_expires_at = None
    case.updated_at = now
    _log(session, case, CaseAction.info_requested, viewer, comment=payload.note.strip())
    session.commit()
    session.expire_all()
    return get_case(case_id, viewer, session)


@router.post("/cases/{case_id}/info-supplied", response_model=CaseDetailOut)
def info_supplied(
    case_id: int,
    payload: InfoSuppliedIn,
    viewer: User = Depends(kyc_reviewer),
    session: Session = Depends(get_session),
) -> dict:
    """Documents arrived (simulated). The case returns to the pool on a new
    cycle, claimable by anyone — not reserved for whoever asked."""
    case = _case(session, case_id)
    if case.status is not CaseStatus.needs_info:
        raise HTTPException(status_code=409, detail="not_awaiting_info")

    now = utcnow()
    case.status = CaseStatus.new
    case.cycles += 1
    case.updated_at = now
    _log(session, case, CaseAction.info_supplied, viewer, comment=payload.note.strip())
    session.commit()
    session.expire_all()
    return get_case(case_id, viewer, session)
