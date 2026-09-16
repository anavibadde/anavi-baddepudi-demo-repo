"""Deactivated managers, sessions that outlive a role change, and queue aging."""

from __future__ import annotations

from datetime import timedelta

from conftest import TEST_PASSWORD, auth
from test_api import listed_ids, submit

from app.entitlements import grant
from app.models import AppRole, AppSlug, User, utcnow
from app.refunds.aging import DUE_HOURS, OVERDUE_HOURS
from app.refunds.models import RefundRequest


def age(session, request_id: int, hours: float) -> None:
    request = session.get(RefundRequest, request_id)
    request.created_at = utcnow() - timedelta(hours=hours)
    session.commit()


def deactivate(client, admin: User, user: User) -> None:
    response = client.patch(f"/api/users/{user.id}", json={"is_active": False}, headers=auth(admin))
    assert response.status_code == 200, response.text


def test_deactivated_managers_queue_falls_to_their_own_manager(client, org, session):
    request = submit(client, org["analyst_a"])
    # Manager B is outside the line either way and stays out of it.
    assert request["id"] not in listed_ids(client, org["manager_b"])

    deactivate(client, org["admin"], org["manager_a"])

    assert request["id"] in listed_ids(client, org["admin"])
    assert request["id"] not in listed_ids(client, org["manager_b"])
    decided = client.post(
        f"/api/refunds/requests/{request['id']}/decision",
        json={"action": "approved"},
        headers=auth(org["admin"]),
    )
    assert decided.status_code == 200


def test_inherited_queue_goes_one_hop_up_not_to_a_stranger(client, org):
    # Manager B is put above Manager A, then Manager A leaves.
    moved = client.patch(
        f"/api/users/{org['manager_a'].id}",
        json={"manager_id": org["manager_b"].id},
        headers=auth(org["admin"]),
    )
    assert moved.status_code == 200
    request = submit(client, org["analyst_a"])
    assert request["id"] not in listed_ids(client, org["manager_b"])

    deactivate(client, org["admin"], org["manager_a"])
    assert request["id"] in listed_ids(client, org["manager_b"])


def test_request_with_no_active_reviewer_is_marked_unassigned(client, org, session):
    orphan = User(name="Orphan", email="orphan@x.com", role=org["analyst_a"].role)
    session.add(orphan)
    session.flush()
    grant(session, orphan, AppSlug.refunds, AppRole.contributor)
    session.commit()

    request = submit(client, orphan)
    seen = client.get(f"/api/refunds/requests/{request['id']}", headers=auth(org["admin"])).json()
    assert seen["unassigned"] is True

    normal = submit(client, org["analyst_a"])
    mine = client.get(f"/api/refunds/requests/{normal['id']}", headers=auth(org["admin"])).json()
    assert mine["unassigned"] is False


def test_deciding_stops_when_the_deciders_account_is_deactivated(client, org, session):
    submit(client, org["analyst_a"])
    manager_headers = auth(org["manager_a"])
    deactivate(client, org["admin"], org["manager_a"])

    # The token was minted before the change and must no longer work at all.
    assert client.get("/api/refunds/requests", headers=manager_headers).status_code == 401


def test_role_change_revokes_live_sessions(client, org):
    headers = auth(org["manager_a"])
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    demoted = client.patch(
        f"/api/users/{org['manager_a'].id}", json={"role": "analyst"}, headers=auth(org["admin"])
    )
    assert demoted.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_only_admins_can_change_a_user(client, org):
    response = client.patch(
        f"/api/users/{org['analyst_a'].id}",
        json={"role": "manager"},
        headers=auth(org["manager_a"]),
    )
    assert response.status_code == 403


def test_deactivated_users_cannot_sign_in(client, org):
    deactivate(client, org["admin"], org["analyst_a"])
    response = client.post(
        "/api/auth/login", json={"user_id": org["analyst_a"].id, "password": TEST_PASSWORD}
    )
    assert response.status_code == 401


def test_pending_requests_age_into_due_then_overdue(client, org, session):
    fresh = submit(client, org["analyst_a"])
    due = submit(client, org["analyst_a"])
    overdue = submit(client, org["analyst_a"])
    age(session, due["id"], DUE_HOURS + 1)
    age(session, overdue["id"], OVERDUE_HOURS + 1)

    rows = client.get("/api/refunds/requests", headers=auth(org["manager_a"])).json()["items"]
    tiers = {row["id"]: row["aging"] for row in rows}
    assert tiers == {fresh["id"]: None, due["id"]: "due", overdue["id"]: "overdue"}
    # Oldest first within the pending block: the SLA breach leads the queue.
    assert [row["id"] for row in rows] == [overdue["id"], due["id"], fresh["id"]]


def test_decided_requests_do_not_age(client, org, session):
    request = submit(client, org["analyst_a"])
    age(session, request["id"], OVERDUE_HOURS + 1)
    client.post(
        f"/api/refunds/requests/{request['id']}/decision",
        json={"action": "approved"},
        headers=auth(org["manager_a"]),
    )

    row = client.get(
        f"/api/refunds/requests/{request['id']}", headers=auth(org["manager_a"])
    ).json()
    assert row["aging"] is None


def test_the_queue_pages_without_losing_rows(client, org):
    ids = [submit(client, org["analyst_a"])["id"] for _ in range(5)]

    first = client.get(
        "/api/refunds/requests", params={"limit": 2}, headers=auth(org["manager_a"])
    ).json()
    assert first["total"] == len(ids)
    assert len(first["items"]) == 2

    rest = client.get(
        "/api/refunds/requests", params={"limit": 10, "offset": 2}, headers=auth(org["manager_a"])
    ).json()
    paged = [row["id"] for row in first["items"]] + [row["id"] for row in rest["items"]]
    assert sorted(paged) == sorted(ids)


def test_page_size_is_capped(client, org):
    response = client.get(
        "/api/refunds/requests", params={"limit": 5000}, headers=auth(org["admin"])
    )
    assert response.status_code == 422
