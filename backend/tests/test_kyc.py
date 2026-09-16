from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import auth
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.entitlements import grant
from app.kyc.models import CaseAction, CaseStatus, KycCase, KycEvent, utcnow
from app.models import AppRole, AppSlug, Role, User


@pytest.fixture()
def case(session: Session, org: dict[str, User]) -> KycCase:
    record = KycCase(
        reference="KYC-1",
        applicant_name="Northwind Ltd",
        country="GB",
        entity_type="company",
        summary="Ownership unclear.",
    )
    session.add(record)
    session.flush()
    session.add(KycEvent(case_id=record.id, action=CaseAction.opened))
    # Two analysts work the pool; two managers can sign off, so a
    # recommendation always has a checker who is not its maker.
    grant(session, org["analyst_a"], AppSlug.kyc, AppRole.contributor)
    grant(session, org["analyst_b"], AppSlug.kyc, AppRole.contributor)
    grant(session, org["manager_a"], AppSlug.kyc, AppRole.reviewer)
    grant(session, org["manager_b"], AppSlug.kyc, AppRole.reviewer)
    session.commit()
    return record


def reload(session: Session, case: KycCase) -> KycCase:
    session.expire_all()
    return session.get(KycCase, case.id)


def claim(client: TestClient, case: KycCase, user: User):
    return client.post(f"/api/kyc/cases/{case.id}/claim", headers=auth(user))


def recommend(client: TestClient, case: KycCase, user: User, outcome: str = "approved"):
    return client.post(
        f"/api/kyc/cases/{case.id}/recommendation",
        json={"recommendation": outcome, "note": "documents checked"},
        headers=auth(user),
    )


def sign_off(client: TestClient, case: KycCase, user: User, approve: bool = True):
    return client.post(
        f"/api/kyc/cases/{case.id}/sign-off",
        json={"approve": approve, "note": "agreed"},
        headers=auth(user),
    )


def test_tool_requires_a_grant(
    client: TestClient, session: Session, org: dict[str, User], case: KycCase
) -> None:
    """Refunds access is not KYC access: the shared login grants neither."""
    refunds_only = User(name="Refunds only", email="ro@x.com", role=Role.analyst, password_hash="x")
    session.add(refunds_only)
    session.flush()
    grant(session, refunds_only, AppSlug.refunds, AppRole.contributor)
    session.commit()
    assert client.get("/api/kyc/cases", headers=auth(refunds_only)).status_code == 404
    assert client.get("/api/kyc/cases", headers=auth(org["analyst_a"])).status_code == 200


def test_queue_is_shared_not_scoped_to_the_org_chart(
    client: TestClient, org: dict[str, User], case: KycCase
) -> None:
    """Refunds hide other people's rows; KYC deliberately does not."""
    for who in ("analyst_a", "analyst_b", "manager_b"):
        rows = client.get("/api/kyc/cases", headers=auth(org[who])).json()
        assert [row["reference"] for row in rows] == ["KYC-1"]


def test_a_claim_locks_the_case_against_everyone_else(
    client: TestClient, session: Session, org: dict[str, User], case: KycCase
) -> None:
    assert claim(client, case, org["analyst_a"]).status_code == 200
    second = claim(client, case, org["analyst_b"])
    assert second.status_code == 409
    assert second.json()["detail"] == "claimed_by_someone_else"
    assert reload(session, case).claimed_by == org["analyst_a"].id


def test_an_abandoned_claim_returns_to_the_pool(
    client: TestClient, session: Session, org: dict[str, User], case: KycCase
) -> None:
    claim(client, case, org["analyst_a"])
    held = reload(session, case)
    held.claim_expires_at = utcnow() - timedelta(minutes=1)
    session.commit()

    taken = claim(client, case, org["analyst_b"])
    assert taken.status_code == 200
    assert taken.json()["claimer"]["id"] == org["analyst_b"].id
    assert [event["action"] for event in taken.json()["events"]][:2] == [
        "claimed",
        "claim_expired",
    ]


def test_releasing_puts_the_case_back(
    client: TestClient, session: Session, org: dict[str, User], case: KycCase
) -> None:
    claim(client, case, org["analyst_a"])
    assert (
        client.post(f"/api/kyc/cases/{case.id}/release", headers=auth(org["analyst_b"])).status_code
        == 403
    )
    released = client.post(f"/api/kyc/cases/{case.id}/release", headers=auth(org["analyst_a"]))
    assert released.status_code == 200
    assert released.json()["status"] == "new"
    assert released.json()["claimer"] is None


def test_only_the_claim_holder_recommends(
    client: TestClient, org: dict[str, User], case: KycCase
) -> None:
    assert recommend(client, case, org["analyst_a"]).json()["detail"] == "claim_required"
    claim(client, case, org["analyst_a"])
    assert recommend(client, case, org["analyst_b"]).json()["detail"] == "not_your_claim"
    assert recommend(client, case, org["analyst_a"]).status_code == 200


def test_a_reviewer_cannot_sign_off_their_own_recommendation(
    client: TestClient, session: Session, org: dict[str, User], case: KycCase
) -> None:
    maker = org["manager_a"]
    claim(client, case, maker)
    recommended = recommend(client, case, maker)
    assert recommended.status_code == 200
    assert recommended.json()["can_sign_off"] is False
    assert recommended.json()["blocked_reason"] == "cannot_sign_off_own_recommendation"

    refused = sign_off(client, case, maker)
    assert refused.status_code == 403
    assert refused.json()["detail"] == "cannot_sign_off_own_recommendation"
    assert reload(session, case).status is CaseStatus.recommended


def test_sign_off_applies_the_recommendation_that_was_made(
    client: TestClient, session: Session, org: dict[str, User], case: KycCase
) -> None:
    claim(client, case, org["analyst_a"])
    recommend(client, case, org["analyst_a"], outcome="rejected")
    signed = sign_off(client, case, org["manager_a"])
    assert signed.status_code == 200
    # The checker agrees or does not; they cannot substitute the other outcome.
    assert signed.json()["status"] == "rejected"
    closed = reload(session, case)
    assert closed.decided_by == org["manager_a"].id
    assert closed.claimed_by is None
    assert [event.action for event in session.query(KycEvent).all()][-1] is CaseAction.rejected


def test_contributors_cannot_sign_off_at_all(
    client: TestClient, org: dict[str, User], case: KycCase
) -> None:
    claim(client, case, org["analyst_a"])
    recommend(client, case, org["analyst_a"])
    assert sign_off(client, case, org["analyst_b"]).status_code == 404


def test_disagreeing_sends_the_case_back_for_a_fresh_review(
    client: TestClient, session: Session, org: dict[str, User], case: KycCase
) -> None:
    claim(client, case, org["analyst_a"])
    recommend(client, case, org["analyst_a"])
    sent_back = sign_off(client, case, org["manager_a"], approve=False)
    assert sent_back.status_code == 200
    assert sent_back.json()["status"] == "new"
    assert sent_back.json()["recommender"] is None
    assert sent_back.json()["cycles"] == 2


def test_needs_info_reopens_the_case_and_keeps_the_history(
    client: TestClient, session: Session, org: dict[str, User], case: KycCase
) -> None:
    claim(client, case, org["analyst_a"])
    recommend(client, case, org["analyst_a"])
    asked = client.post(
        f"/api/kyc/cases/{case.id}/needs-info",
        json={"note": "send a bank statement"},
        headers=auth(org["manager_a"]),
    )
    assert asked.status_code == 200
    assert asked.json()["status"] == "needs_info"

    supplied = client.post(
        f"/api/kyc/cases/{case.id}/info-supplied",
        json={"note": "statement received"},
        headers=auth(org["analyst_b"]),
    )
    assert supplied.status_code == 200
    assert supplied.json()["status"] == "new"
    assert supplied.json()["cycles"] == 2

    # The second cycle starts clean but the first cycle's events survive.
    claim(client, case, org["analyst_b"])
    final = recommend(client, case, org["analyst_b"]).json()
    cycles = {event["cycle"] for event in final["events"]}
    assert cycles == {1, 2}
    assert [event["action"] for event in final["events"]].count("recommended") == 2


def test_a_case_mid_flight_cannot_be_claimed_out_from_under_the_flow(
    client: TestClient, org: dict[str, User], case: KycCase
) -> None:
    claim(client, case, org["analyst_a"])
    recommend(client, case, org["analyst_a"])
    # Claiming a recommended case would drop the recommendation the checker is
    # about to act on.
    awaiting = claim(client, case, org["analyst_b"])
    assert awaiting.status_code == 409
    assert awaiting.json()["detail"] == "awaiting_sign_off"

    client.post(
        f"/api/kyc/cases/{case.id}/needs-info",
        json={"note": "send a bank statement"},
        headers=auth(org["manager_a"]),
    )
    parked = claim(client, case, org["analyst_b"])
    assert parked.status_code == 409
    assert parked.json()["detail"] == "awaiting_info"


def test_a_decided_case_is_closed_for_good(
    client: TestClient, org: dict[str, User], case: KycCase
) -> None:
    claim(client, case, org["analyst_a"])
    recommend(client, case, org["analyst_a"])
    sign_off(client, case, org["manager_a"])
    assert claim(client, case, org["analyst_b"]).status_code == 409
    assert sign_off(client, case, org["manager_b"]).status_code == 409


def test_a_kyc_grant_does_not_open_refunds(
    client: TestClient, session: Session, org: dict[str, User], case: KycCase
) -> None:
    outsider = User(name="KYC only", email="kyc@x.com", role=Role.analyst, password_hash="x")
    session.add(outsider)
    session.flush()
    grant(session, outsider, AppSlug.kyc, AppRole.reviewer)
    session.commit()
    headers = auth(outsider)
    assert client.get("/api/kyc/cases", headers=headers).status_code == 200
    assert client.get("/api/refunds/requests", headers=headers).status_code == 404
