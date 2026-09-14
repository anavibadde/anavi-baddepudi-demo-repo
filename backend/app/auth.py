"""Password hashing and session tokens.

Demo-grade but not a toy: passwords are salted and stretched, tokens are random
and stored server-side so logging out actually revokes them. What a real
deployment still needs on top: SSO or a password reset path, rate limiting on
login, and cookies with the Secure/HttpOnly flags instead of a bearer token
handed to JavaScript.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .models import Session, User

ITERATIONS = 120_000
SESSION_HOURS = 12


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    # Constant time: a plain == leaks how much of the hash matched.
    return hmac.compare_digest(digest.hex(), expected)


def authenticate(session: DbSession, *, user_id: int, password: str) -> User | None:
    user = session.get(User, user_id)
    if user is None:
        # Hash anyway so a missing id doesn't answer faster than a wrong password.
        verify_password(password, hash_password("nobody"))
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def issue_token(session: DbSession, user: User) -> Session:
    now = datetime.now(timezone.utc)
    session.execute(delete(Session).where(Session.expires_at < now))
    record = Session(
        token=secrets.token_urlsafe(32),
        user_id=user.id,
        created_at=now,
        expires_at=now + timedelta(hours=SESSION_HOURS),
    )
    session.add(record)
    session.commit()
    return record


def user_for_token(session: DbSession, token: str) -> User | None:
    record = session.scalar(select(Session).where(Session.token == token))
    if record is None:
        return None
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        session.delete(record)
        session.commit()
        return None
    if not record.user.is_active:
        session.delete(record)
        session.commit()
        return None
    return record.user


def revoke_token(session: DbSession, token: str) -> None:
    session.execute(delete(Session).where(Session.token == token))
    session.commit()


def revoke_user_sessions(session: DbSession, user_id: int) -> None:
    """Drop every live session for a user. Called whenever their role, manager
    or active state changes: a token minted as a manager must not keep manager
    powers for the rest of its twelve hours."""
    session.execute(delete(Session).where(Session.user_id == user_id))
