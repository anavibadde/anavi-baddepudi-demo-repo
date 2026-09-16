"""Request-scoped identity and access checks every route depends on."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .auth import user_for_token
from .db import get_session
from .entitlements import effective_role, holds
from .models import AppRole, AppSlug, User


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


def require_app(app: AppSlug, minimum: AppRole = AppRole.viewer) -> Callable[..., User]:
    """Gate a route on holding a tool, at a given level inside it.

    Hiding a tile on the home page is decoration; this is the check. A caller
    without the grant gets 404 rather than 403, matching how the tools answer
    for records outside their scope — a refused 403 still confirms the tool and
    the record exist.
    """

    def dependency(
        viewer: User = Depends(current_user),
        session: Session = Depends(get_session),
    ) -> User:
        if not holds(effective_role(session, viewer, app), minimum):
            raise HTTPException(status_code=404, detail="not_found")
        return viewer

    return dependency
