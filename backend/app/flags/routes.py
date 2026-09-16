from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from ..db import get_session
from ..deps import require_app
from ..entitlements import effective_role, holds
from ..models import AppRole, AppSlug, User
from ..schemas import UserOut
from .models import (
    ChangeStatus,
    Environment,
    FeatureFlag,
    FlagAction,
    FlagChangeRequest,
    FlagEvent,
    FlagState,
    utcnow,
)
from .rules import FlagDenied, check_can_decide, check_can_withdraw, check_direct_change
from .schemas import (
    ChangeRequestIn,
    ChangeRequestOut,
    DecisionIn,
    EventOut,
    FlagDetailOut,
    FlagOut,
    SetStateIn,
    StateOut,
)

router = APIRouter(prefix="/api/flags", tags=["flags"])

flags_user = require_app(AppSlug.flags, AppRole.viewer)
flags_editor = require_app(AppSlug.flags, AppRole.contributor)
flags_approver = require_app(AppSlug.flags, AppRole.reviewer)


def _state(session: Session, flag_id: int, environment: Environment) -> FlagState:
    state = session.scalar(
        select(FlagState).where(FlagState.flag_id == flag_id, FlagState.environment == environment)
    )
    if state is None:
        raise HTTPException(status_code=404, detail="not_found")
    return state


def _serialize_request(
    viewer: User, request: FlagChangeRequest, state: FlagState
) -> ChangeRequestOut:
    blocked: str | None = None
    try:
        check_can_decide(viewer, request, state)
    except FlagDenied as denied:
        blocked = denied.reason
    return ChangeRequestOut(
        id=request.id,
        flag_id=request.flag_id,
        flag_key=request.flag.key,
        environment=request.environment,
        from_value=request.from_value,
        to_value=request.to_value,
        reason=request.reason,
        status=request.status,
        requester=UserOut.model_validate(request.requester),
        requested_at=request.requested_at,
        decider=UserOut.model_validate(request.decider) if request.decider else None,
        decided_at=request.decided_at,
        decision_note=request.decision_note,
        stale=state.enabled != request.from_value,
        can_decide=blocked is None,
        decide_blocked_reason=blocked,
    )


def _pending_for(session: Session, flag: FeatureFlag) -> list[FlagChangeRequest]:
    return list(
        session.scalars(
            select(FlagChangeRequest)
            .where(
                FlagChangeRequest.flag_id == flag.id,
                FlagChangeRequest.status == ChangeStatus.pending,
            )
            .order_by(FlagChangeRequest.id)
        )
    )


def _serialize(viewer: User, session: Session, flag: FeatureFlag) -> dict:
    states = {state.environment: state for state in flag.states}
    return {
        "id": flag.id,
        "key": flag.key,
        "name": flag.name,
        "description": flag.description,
        "states": [
            StateOut(
                environment=environment,
                enabled=states[environment].enabled,
                updated_at=states[environment].updated_at,
                updated_by=(
                    UserOut.model_validate(states[environment].updater)
                    if states[environment].updater
                    else None
                ),
            )
            for environment in Environment
            if environment in states
        ],
        "pending": [
            _serialize_request(viewer, request, states[request.environment])
            for request in _pending_for(session, flag)
        ],
    }


@router.get("/config")
def get_config(
    viewer: User = Depends(flags_user),
    session: Session = Depends(get_session),
) -> dict:
    role = effective_role(session, viewer, AppSlug.flags)
    return {
        "environments": [environment.value for environment in Environment],
        "can_edit": holds(role, AppRole.contributor),
        "can_approve": holds(role, AppRole.reviewer),
    }


@router.get("/flags", response_model=list[FlagOut])
def list_flags(
    viewer: User = Depends(flags_user),
    session: Session = Depends(get_session),
) -> list[dict]:
    flags = session.scalars(
        select(FeatureFlag)
        .options(selectinload(FeatureFlag.states).selectinload(FlagState.updater))
        .order_by(FeatureFlag.key)
    )
    return [_serialize(viewer, session, flag) for flag in flags]


@router.get("/flags/{flag_id}", response_model=FlagDetailOut)
def get_flag(
    flag_id: int,
    viewer: User = Depends(flags_user),
    session: Session = Depends(get_session),
) -> dict:
    flag = session.get(FeatureFlag, flag_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="not_found")
    data = _serialize(viewer, session, flag)
    events = session.scalars(
        select(FlagEvent).where(FlagEvent.flag_id == flag.id).order_by(FlagEvent.id.desc())
    )
    data["events"] = [
        EventOut(
            id=event.id,
            action=event.action,
            environment=event.environment,
            from_value=event.from_value,
            to_value=event.to_value,
            comment=event.comment,
            actor=UserOut.model_validate(event.actor),
            created_at=event.created_at,
        )
        for event in events
    ]
    return data


@router.post("/flags/{flag_id}/state", response_model=FlagDetailOut)
def set_state(
    flag_id: int,
    payload: SetStateIn,
    viewer: User = Depends(flags_editor),
    session: Session = Depends(get_session),
) -> dict:
    """Move a flag directly. Dev only — prod goes through a change request."""
    flag = session.get(FeatureFlag, flag_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        check_direct_change(payload.environment)
    except FlagDenied as denied:
        raise HTTPException(status_code=denied.status_code, detail=denied.reason) from denied

    state = _state(session, flag_id, payload.environment)
    before = state.enabled
    if before == payload.enabled:
        raise HTTPException(status_code=409, detail="no_change")

    # Conditional on the value we read: two people toggling at once means the
    # second write loses rather than silently landing on a stale read.
    result = session.execute(
        update(FlagState)
        .where(FlagState.id == state.id, FlagState.enabled == before)
        .values(enabled=payload.enabled, updated_at=utcnow(), updated_by=viewer.id)
    )
    if result.rowcount == 0:
        session.rollback()
        raise HTTPException(status_code=409, detail="state_moved")

    session.add(
        FlagEvent(
            flag_id=flag_id,
            environment=payload.environment,
            action=FlagAction.set_directly,
            from_value=before,
            to_value=payload.enabled,
            comment=payload.reason.strip(),
            actor_id=viewer.id,
        )
    )
    session.commit()
    session.expire_all()
    return get_flag(flag_id, viewer, session)


@router.post("/flags/{flag_id}/requests", response_model=FlagDetailOut, status_code=201)
def request_change(
    flag_id: int,
    payload: ChangeRequestIn,
    viewer: User = Depends(flags_editor),
    session: Session = Depends(get_session),
) -> dict:
    flag = session.get(FeatureFlag, flag_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="not_found")
    if payload.environment is not Environment.prod:
        raise HTTPException(status_code=400, detail="direct_change_available")
    if payload.from_value == payload.to_value:
        raise HTTPException(status_code=400, detail="no_change")

    state = _state(session, flag_id, payload.environment)
    if state.enabled != payload.from_value:
        # The proposal was written against a value prod no longer holds.
        raise HTTPException(status_code=409, detail="stale_request")
    open_request = session.scalar(
        select(FlagChangeRequest).where(
            FlagChangeRequest.flag_id == flag_id,
            FlagChangeRequest.environment == payload.environment,
            FlagChangeRequest.status == ChangeStatus.pending,
        )
    )
    if open_request is not None:
        raise HTTPException(status_code=409, detail="request_already_open")

    request = FlagChangeRequest(
        flag_id=flag_id,
        environment=payload.environment,
        from_value=payload.from_value,
        to_value=payload.to_value,
        reason=payload.reason.strip(),
        requested_by=viewer.id,
    )
    session.add(request)
    session.flush()
    session.add(
        FlagEvent(
            flag_id=flag_id,
            environment=payload.environment,
            action=FlagAction.proposed,
            from_value=payload.from_value,
            to_value=payload.to_value,
            comment=payload.reason.strip(),
            actor_id=viewer.id,
            request_id=request.id,
        )
    )
    session.commit()
    session.expire_all()
    return get_flag(flag_id, viewer, session)


@router.get("/requests", response_model=list[ChangeRequestOut])
def list_requests(
    viewer: User = Depends(flags_user),
    session: Session = Depends(get_session),
) -> list[ChangeRequestOut]:
    requests = session.scalars(
        select(FlagChangeRequest)
        .where(FlagChangeRequest.status == ChangeStatus.pending)
        .order_by(FlagChangeRequest.id)
    )
    return [
        _serialize_request(viewer, request, _state(session, request.flag_id, request.environment))
        for request in requests
    ]


@router.post("/requests/{request_id}/decision", response_model=FlagDetailOut)
def decide(
    request_id: int,
    payload: DecisionIn,
    viewer: User = Depends(flags_approver),
    session: Session = Depends(get_session),
) -> dict:
    """Approving is the only place configuration moves in prod, and it applies
    exactly the proposed transition — never the caller's idea of it."""
    request = session.get(FlagChangeRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="not_found")
    state = _state(session, request.flag_id, request.environment)

    if payload.approve:
        try:
            check_can_decide(viewer, request, state)
        except FlagDenied as denied:
            raise HTTPException(status_code=denied.status_code, detail=denied.reason) from denied
    else:
        if request.status is not ChangeStatus.pending:
            raise HTTPException(status_code=409, detail="already_decided")
        if request.requested_by == viewer.id:
            raise HTTPException(status_code=403, detail="cannot_approve_own_request")

    decided_at = utcnow()
    closed = session.execute(
        update(FlagChangeRequest)
        .where(
            FlagChangeRequest.id == request.id,
            FlagChangeRequest.status == ChangeStatus.pending,
        )
        .values(
            status=ChangeStatus.applied if payload.approve else ChangeStatus.rejected,
            decided_by=viewer.id,
            decided_at=decided_at,
            decision_note=payload.note.strip(),
        )
    )
    if closed.rowcount == 0:
        session.rollback()
        raise HTTPException(status_code=409, detail="already_decided")

    if payload.approve:
        # Bound to from_value again at write time: between the check above and
        # here is the window where prod could move, and this closes it.
        applied = session.execute(
            update(FlagState)
            .where(FlagState.id == state.id, FlagState.enabled == request.from_value)
            .values(enabled=request.to_value, updated_at=decided_at, updated_by=viewer.id)
        )
        if applied.rowcount == 0:
            session.rollback()
            raise HTTPException(status_code=409, detail="stale_request")

    session.add(
        FlagEvent(
            flag_id=request.flag_id,
            environment=request.environment,
            action=FlagAction.applied if payload.approve else FlagAction.rejected,
            from_value=request.from_value,
            to_value=request.to_value if payload.approve else None,
            comment=payload.note.strip(),
            actor_id=viewer.id,
            request_id=request.id,
        )
    )
    session.commit()
    session.expire_all()
    return get_flag(request.flag_id, viewer, session)


@router.post("/requests/{request_id}/withdraw", response_model=FlagDetailOut)
def withdraw(
    request_id: int,
    viewer: User = Depends(flags_editor),
    session: Session = Depends(get_session),
) -> dict:
    request = session.get(FlagChangeRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        check_can_withdraw(viewer, request)
    except FlagDenied as denied:
        raise HTTPException(status_code=denied.status_code, detail=denied.reason) from denied

    request.status = ChangeStatus.withdrawn
    request.decided_at = utcnow()
    session.add(
        FlagEvent(
            flag_id=request.flag_id,
            environment=request.environment,
            action=FlagAction.withdrawn,
            from_value=request.from_value,
            to_value=request.to_value,
            actor_id=viewer.id,
            request_id=request.id,
        )
    )
    session.commit()
    session.expire_all()
    return get_flag(request.flag_id, viewer, session)


@router.get("/effective/{environment}")
def effective(
    environment: Environment,
    _: User = Depends(flags_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    """What the demo surface reads. Deliberately the same rows the approval
    writes, so the panel is showing configuration rather than a mock."""
    rows = session.execute(
        select(FeatureFlag.key, FlagState.enabled)
        .join(FlagState, FlagState.flag_id == FeatureFlag.id)
        .where(FlagState.environment == environment)
        .order_by(FeatureFlag.key)
    )
    return {key: enabled for key, enabled in rows}
