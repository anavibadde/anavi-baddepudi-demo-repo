"""The platform shell: one login, one users table, several tools behind it."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import (
    authenticate,
    issue_token,
    revoke_token,
    revoke_user_sessions,
)
from .db import create_all, get_session
from .deps import bearer_token, current_user
from .entitlements import apps_for
from .models import Role, User
from .refunds.routes import router as refunds_router
from .schemas import AppOut, LoginIn, LoginOut, SwitchIn, UserOut, UserUpdate

# Impersonation without a password is a backdoor, so it is a deployment choice
# rather than a code path that always exists. On here so the demo can be walked
# through from one screen; set DEMO_SWITCH=0 and the endpoint 404s.
DEMO_SWITCH = os.getenv("DEMO_SWITCH", "1").lower() not in {"0", "false", "no"}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_all()
    yield


app = FastAPI(title="Internal tools (demo)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(refunds_router)


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


@app.get("/api/me/apps", response_model=list[AppOut])
def my_apps(
    viewer: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[dict]:
    """The tools this person holds. The home page renders these and nothing
    else, but the grant is re-checked on every call into a tool."""
    return [
        {
            "slug": info.slug,
            "name": info.name,
            "description": info.description,
            "path": info.path,
            "app_role": app_role,
        }
        for info, app_role in apps_for(session, viewer)
    ]


@app.get("/api/config")
def get_config() -> dict:
    return {
        "demo_switch": DEMO_SWITCH,
        "demo_notice": (
            "Demo only — sign-in is a seeded password and the identity switcher "
            "is a backdoor. No refunds are executed and no money moves."
        ),
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
