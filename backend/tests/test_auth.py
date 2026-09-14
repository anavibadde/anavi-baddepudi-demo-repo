from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import TEST_PASSWORD, auth

from app.auth import hash_password, verify_password
from app.db import SessionLocal
from app.models import Session as SessionRecord


def login(client, user, password=TEST_PASSWORD):
    return client.post("/api/auth/login", json={"user_id": user.id, "password": password})


def test_password_hashes_are_salted_and_verifiable():
    first = hash_password("hunter2")
    second = hash_password("hunter2")

    assert first != second  # different salts
    assert "hunter2" not in first
    assert verify_password("hunter2", first)
    assert not verify_password("hunter3", first)


def test_login_returns_a_token_that_identifies_the_user(client, org):
    response = login(client, org["analyst_a"])
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == org["analyst_a"].email

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == org["analyst_a"].id


def test_wrong_password_and_unknown_id_are_indistinguishable(client, org):
    wrong_password = login(client, org["analyst_a"], password="nope")
    assert wrong_password.status_code == 401

    unknown = client.post("/api/auth/login", json={"user_id": 9999, "password": TEST_PASSWORD})
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == wrong_password.json()["detail"]


def test_logout_revokes_the_token(client, org):
    headers = auth(org["manager_a"])
    assert client.get("/api/requests", headers=headers).status_code == 200

    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/requests", headers=headers).status_code == 401


def test_expired_token_is_rejected(client, org):
    headers = auth(org["manager_a"])
    token = headers["Authorization"].removeprefix("Bearer ")
    with SessionLocal() as session:
        record = session.get(SessionRecord, token)
        record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()

    assert client.get("/api/requests", headers=headers).status_code == 401


def test_demo_switch_hands_back_a_real_session_for_the_target(client, org):
    headers = auth(org["analyst_a"])
    response = client.post(
        "/api/auth/switch", json={"user_id": org["manager_a"].id}, headers=headers
    )
    assert response.status_code == 200
    switched = {"Authorization": f"Bearer {response.json()['token']}"}

    assert client.get("/api/auth/me", headers=switched).json()["id"] == org["manager_a"].id
    # The identity you left behind goes with it, rather than staying live.
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_demo_switch_needs_a_session_and_an_active_target(client, org, session):
    assert client.post("/api/auth/switch", json={"user_id": org["admin"].id}).status_code == 401

    org["manager_b"].is_active = False
    session.commit()
    blocked = client.post(
        "/api/auth/switch", json={"user_id": org["manager_b"].id}, headers=auth(org["analyst_a"])
    )
    assert blocked.status_code == 400


def test_token_decides_the_queue_not_a_client_supplied_id(client, org):
    """The old X-User-Id header must not be able to change who you are."""
    headers = {**auth(org["analyst_a"]), "X-User-Id": str(org["admin"].id)}
    me = client.get("/api/auth/me", headers=headers)
    assert me.json()["id"] == org["analyst_a"].id
