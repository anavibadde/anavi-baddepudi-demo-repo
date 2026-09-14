from __future__ import annotations

import pytest
from conftest import auth
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.entitlements import grant
from app.flags.models import ChangeStatus, Environment, FeatureFlag, FlagChangeRequest, FlagState
from app.models import AppRole, AppSlug, User


@pytest.fixture()
def flag(session: Session, org: dict[str, User]) -> FeatureFlag:
    record = FeatureFlag(key="checkout.express", name="Express", description="")
    session.add(record)
    session.flush()
    session.add_all(
        [
            FlagState(flag_id=record.id, environment=Environment.dev, enabled=False),
            FlagState(flag_id=record.id, environment=Environment.prod, enabled=False),
        ]
    )
    # manager_a proposes, manager_b approves: maker-checker needs two people.
    grant(session, org["manager_a"], AppSlug.flags, AppRole.contributor)
    grant(session, org["manager_b"], AppSlug.flags, AppRole.reviewer)
    grant(session, org["analyst_a"], AppSlug.flags, AppRole.viewer)
    session.commit()
    return record


def prod_state(session: Session, flag_id: int) -> bool:
    session.expire_all()
    state = session.query(FlagState).filter_by(flag_id=flag_id, environment=Environment.prod).one()
    return state.enabled


def propose(client: TestClient, flag: FeatureFlag, user: User, **kwargs) -> dict:
    body = {"environment": "prod", "from_value": False, "to_value": True, "reason": "soaked"}
    body.update(kwargs)
    return client.post(f"/api/flags/flags/{flag.id}/requests", json=body, headers=auth(user))


def test_tool_requires_a_grant(client: TestClient, org: dict[str, User], flag: FeatureFlag) -> None:
    assert client.get("/api/flags/flags", headers=auth(org["analyst_b"])).status_code == 404


def test_dev_moves_directly_but_prod_does_not(
    client: TestClient, session: Session, org: dict[str, User], flag: FeatureFlag
) -> None:
    editor = auth(org["manager_a"])
    dev = client.post(
        f"/api/flags/flags/{flag.id}/state",
        json={"environment": "dev", "enabled": True},
        headers=editor,
    )
    assert dev.status_code == 200
    assert [s for s in dev.json()["states"] if s["environment"] == "dev"][0]["enabled"] is True

    prod = client.post(
        f"/api/flags/flags/{flag.id}/state",
        json={"environment": "prod", "enabled": True},
        headers=editor,
    )
    assert prod.status_code == 400
    assert prod.json()["detail"] == "prod_requires_request"
    assert prod_state(session, flag.id) is False


def test_viewer_cannot_change_anything(
    client: TestClient, org: dict[str, User], flag: FeatureFlag
) -> None:
    viewer = auth(org["analyst_a"])
    assert client.get("/api/flags/flags", headers=viewer).status_code == 200
    denied = client.post(
        f"/api/flags/flags/{flag.id}/state",
        json={"environment": "dev", "enabled": True},
        headers=viewer,
    )
    assert denied.status_code == 404


def test_requester_cannot_approve_their_own_change(
    client: TestClient, session: Session, org: dict[str, User], flag: FeatureFlag
) -> None:
    # The proposer also holds reviewer here, so only the maker-checker rule
    # stands between them and applying their own change.
    grant(session, org["manager_a"], AppSlug.flags, AppRole.reviewer)
    session.commit()
    assert propose(client, flag, org["manager_a"]).status_code == 201
    request_id = session.query(FlagChangeRequest).one().id

    denied = client.post(
        f"/api/flags/requests/{request_id}/decision",
        json={"approve": True},
        headers=auth(org["manager_a"]),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "cannot_approve_own_request"
    assert prod_state(session, flag.id) is False


def test_approval_applies_the_exact_change(
    client: TestClient, session: Session, org: dict[str, User], flag: FeatureFlag
) -> None:
    assert propose(client, flag, org["manager_a"]).status_code == 201
    request_id = session.query(FlagChangeRequest).one().id

    applied = client.post(
        f"/api/flags/requests/{request_id}/decision",
        json={"approve": True, "note": "ok"},
        headers=auth(org["manager_b"]),
    )
    assert applied.status_code == 200
    assert prod_state(session, flag.id) is True
    session.expire_all()
    assert session.get(FlagChangeRequest, request_id).status is ChangeStatus.applied

    effective = client.get("/api/flags/effective/prod", headers=auth(org["manager_b"]))
    assert effective.json()["checkout.express"] is True
    # The applied transition is on the log, not just in the state row.
    actions = [event["action"] for event in applied.json()["events"]]
    assert "applied" in actions and "proposed" in actions


def test_approval_refuses_when_prod_moved_underneath_it(
    client: TestClient, session: Session, org: dict[str, User], flag: FeatureFlag
) -> None:
    assert propose(client, flag, org["manager_a"]).status_code == 201
    request_id = session.query(FlagChangeRequest).one().id

    # Someone turns prod on by another route; the pending request was written
    # against "off", so applying it now would rubber-stamp an unreviewed value.
    state = session.query(FlagState).filter_by(flag_id=flag.id, environment=Environment.prod).one()
    state.enabled = True
    session.commit()

    stale = client.post(
        f"/api/flags/requests/{request_id}/decision",
        json={"approve": True},
        headers=auth(org["manager_b"]),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "stale_request"
    session.expire_all()
    assert session.get(FlagChangeRequest, request_id).status is ChangeStatus.pending


def test_rejecting_leaves_configuration_alone(
    client: TestClient, session: Session, org: dict[str, User], flag: FeatureFlag
) -> None:
    assert propose(client, flag, org["manager_a"]).status_code == 201
    request_id = session.query(FlagChangeRequest).one().id

    rejected = client.post(
        f"/api/flags/requests/{request_id}/decision",
        json={"approve": False, "note": "not this week"},
        headers=auth(org["manager_b"]),
    )
    assert rejected.status_code == 200
    assert prod_state(session, flag.id) is False
    session.expire_all()
    assert session.get(FlagChangeRequest, request_id).status is ChangeStatus.rejected

    again = client.post(
        f"/api/flags/requests/{request_id}/decision",
        json={"approve": True},
        headers=auth(org["manager_b"]),
    )
    assert again.status_code == 409


def test_one_open_request_per_flag_and_environment(
    client: TestClient, org: dict[str, User], flag: FeatureFlag
) -> None:
    assert propose(client, flag, org["manager_a"]).status_code == 201
    second = propose(client, flag, org["manager_a"])
    assert second.status_code == 409
    assert second.json()["detail"] == "request_already_open"


def test_proposal_must_match_current_value(
    client: TestClient, org: dict[str, User], flag: FeatureFlag
) -> None:
    wrong = propose(client, flag, org["manager_a"], from_value=True, to_value=False)
    assert wrong.status_code == 409
    assert wrong.json()["detail"] == "stale_request"


def test_requester_can_withdraw_their_own_only(
    client: TestClient, session: Session, org: dict[str, User], flag: FeatureFlag
) -> None:
    assert propose(client, flag, org["manager_a"]).status_code == 201
    request_id = session.query(FlagChangeRequest).one().id

    grant(session, org["analyst_a"], AppSlug.flags, AppRole.contributor)
    session.commit()
    denied = client.post(
        f"/api/flags/requests/{request_id}/withdraw", headers=auth(org["analyst_a"])
    )
    assert denied.status_code == 403

    ok = client.post(f"/api/flags/requests/{request_id}/withdraw", headers=auth(org["manager_a"]))
    assert ok.status_code == 200
    session.expire_all()
    assert session.get(FlagChangeRequest, request_id).status is ChangeStatus.withdrawn


def test_flags_grant_does_not_open_refunds(
    client: TestClient, session: Session, org: dict[str, User], flag: FeatureFlag
) -> None:
    analyst = org["analyst_a"]
    for entitlement in list(analyst.entitlements):
        if entitlement.app is AppSlug.refunds:
            session.delete(entitlement)
    session.commit()
    assert client.get("/api/flags/flags", headers=auth(analyst)).status_code == 200
    assert client.get("/api/refunds/requests", headers=auth(analyst)).status_code == 404
