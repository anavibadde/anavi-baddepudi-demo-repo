from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test.db")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.auth import hash_password, issue_token  # noqa: E402
from app.db import SessionLocal, create_all, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Role, User  # noqa: E402

TEST_PASSWORD = "test-password"


def auth(user: User) -> dict[str, str]:
    """Headers for an authenticated request, minting a token directly so the
    tests are not paying pbkdf2 on every call."""
    with SessionLocal() as session:
        record = issue_token(session, session.get(User, user.id))
        return {"Authorization": f"Bearer {record.token}"}


@pytest.fixture()
def session() -> Iterator[Session]:
    Base.metadata.drop_all(engine)
    create_all()
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def org(session: Session) -> dict[str, User]:
    """admin -> manager_a, manager_b; analysts under each."""
    pw = hash_password(TEST_PASSWORD)
    admin = User(name="Admin", email="admin@x.com", role=Role.admin, password_hash=pw)
    session.add(admin)
    session.flush()
    manager_a = User(
        name="Manager A", email="ma@x.com", role=Role.manager, manager_id=admin.id, password_hash=pw
    )
    manager_b = User(
        name="Manager B", email="mb@x.com", role=Role.manager, manager_id=admin.id, password_hash=pw
    )
    session.add_all([manager_a, manager_b])
    session.flush()
    analyst_a = User(
        name="Analyst A",
        email="aa@x.com",
        role=Role.analyst,
        manager_id=manager_a.id,
        password_hash=pw,
    )
    analyst_b = User(
        name="Analyst B",
        email="ab@x.com",
        role=Role.analyst,
        manager_id=manager_b.id,
        password_hash=pw,
    )
    session.add_all([analyst_a, analyst_b])
    session.commit()
    return {
        "admin": admin,
        "manager_a": manager_a,
        "manager_b": manager_b,
        "analyst_a": analyst_a,
        "analyst_b": analyst_b,
    }


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client
