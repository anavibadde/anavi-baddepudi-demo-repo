from __future__ import annotations

import pytest

BASE = {
    "customer_id": "CUS-1",
    "customer_name": "Test Customer",
    "order_id": "ORD-1",
    "reason": "duplicate_charge",
    "amount_cents": 5_000,
    "note": "Charged twice.",
}


def submit(client, user, **overrides):
    payload = {**BASE, **overrides}
    response = client.post("/api/requests", json=payload, headers={"X-User-Id": str(user.id)})
    assert response.status_code == 201, response.text
    return response.json()


def decide(client, user, request_id, action, **payload):
    return client.post(
        f"/api/requests/{request_id}/decision",
        json={"action": action, **payload},
        headers={"X-User-Id": str(user.id)},
    )


def listed_ids(client, user, **params):
    response = client.get("/api/requests", params=params, headers={"X-User-Id": str(user.id)})
    assert response.status_code == 200, response.text
    return [r["id"] for r in response.json()]


def test_analyst_sees_only_their_own(client, org):
    mine = submit(client, org["analyst_a"])
    theirs = submit(client, org["analyst_b"])

    ids = listed_ids(client, org["analyst_a"])
    assert ids == [mine["id"]]
    assert theirs["id"] not in ids


def test_manager_sees_direct_reports_and_admin_sees_all(client, org):
    from_a = submit(client, org["analyst_a"])
    from_b = submit(client, org["analyst_b"])

    assert listed_ids(client, org["manager_a"]) == [from_a["id"]]
    assert sorted(listed_ids(client, org["admin"])) == sorted([from_a["id"], from_b["id"]])


def test_out_of_line_request_is_404_not_403(client, org):
    other = submit(client, org["analyst_b"])
    response = client.get(
        f"/api/requests/{other['id']}", headers={"X-User-Id": str(org["manager_a"].id)}
    )
    assert response.status_code == 404


def test_submitter_cannot_decide_their_own_request(client, org):
    own = submit(client, org["manager_a"])

    denied = decide(client, org["manager_a"], own["id"], "approved")
    assert denied.status_code == 403
    assert denied.json()["detail"] == "cannot_decide_own_request"

    # The submitter's own manager reviews it instead.
    allowed = decide(client, org["admin"], own["id"], "approved")
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "approved"


def test_analyst_cannot_decide(client, org):
    request = submit(client, org["analyst_a"])
    response = decide(client, org["analyst_a"], request["id"], "approved")
    assert response.status_code == 403
    assert response.json()["detail"] == "analysts_cannot_decide"


def test_a_request_is_decided_once(client, org):
    request = submit(client, org["analyst_a"])
    assert decide(client, org["manager_a"], request["id"], "approved").status_code == 200

    second = decide(client, org["admin"], request["id"], "rejected", comment="changed my mind")
    assert second.status_code == 409
    assert second.json()["detail"] == "already_decided"


def test_rejection_requires_a_comment(client, org):
    request = submit(client, org["analyst_a"])
    assert decide(client, org["manager_a"], request["id"], "rejected").status_code == 400

    ok = decide(client, org["manager_a"], request["id"], "rejected", comment="Outside the window.")
    assert ok.status_code == 200
    assert ok.json()["status"] == "rejected"


def test_history_records_submission_and_decision(client, org):
    request = submit(client, org["analyst_a"])
    decide(client, org["manager_a"], request["id"], "approved", comment="Verified.")

    detail = client.get(
        f"/api/requests/{request['id']}", headers={"X-User-Id": str(org["analyst_a"].id)}
    ).json()
    assert [e["action"] for e in detail["events"]] == ["submitted", "approved"]
    assert detail["events"][1]["actor"]["email"] == org["manager_a"].email


def test_high_value_needs_explicit_confirmation(client, org):
    request = submit(client, org["analyst_a"], amount_cents=250_000)
    assert request["risk_flags"] == ["high_value"]

    unconfirmed = decide(client, org["manager_a"], request["id"], "approved")
    assert unconfirmed.status_code == 400
    assert unconfirmed.json()["detail"] == "risk_confirmation_required"

    confirmed = decide(client, org["manager_a"], request["id"], "approved", confirm_risk=True)
    assert confirmed.status_code == 200


def test_rejecting_a_flagged_request_needs_no_confirmation(client, org):
    request = submit(client, org["analyst_a"], amount_cents=250_000)
    response = decide(client, org["manager_a"], request["id"], "rejected", comment="Not ours.")
    assert response.status_code == 200


def test_high_value_plus_another_flag_escalates_to_admin(client, org):
    request = submit(client, org["analyst_a"], amount_cents=250_000, reason="fraud_dispute")
    assert set(request["risk_flags"]) == {"high_value", "fraud_dispute"}
    assert request["requires_admin"] is True

    denied = decide(client, org["manager_a"], request["id"], "approved", confirm_risk=True)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "admin_approval_required"

    allowed = decide(client, org["admin"], request["id"], "approved", confirm_risk=True)
    assert allowed.status_code == 200


def test_rapid_succession_flag(client, org):
    submit(client, org["analyst_a"], customer_id="CUS-9")
    submit(client, org["analyst_a"], customer_id="CUS-9")
    third = submit(client, org["analyst_a"], customer_id="CUS-9")
    assert "rapid_succession" in third["risk_flags"]


def test_repeat_customer_flag_counts_approved_refunds(client, org):
    for _ in range(2):
        prior = submit(client, org["analyst_a"], customer_id="CUS-7")
        decide(client, org["manager_a"], prior["id"], "approved")

    latest = submit(client, org["analyst_a"], customer_id="CUS-7")
    assert "repeat_customer" in latest["risk_flags"]


def test_idempotency_key_does_not_duplicate(client, org):
    first = submit(client, org["analyst_a"], idempotency_key="abc-123")
    second = submit(client, org["analyst_a"], idempotency_key="abc-123")
    assert first["id"] == second["id"]
    assert listed_ids(client, org["analyst_a"]) == [first["id"]]


@pytest.mark.parametrize("status", ["pending", "approved"])
def test_status_filter(client, org, status):
    pending = submit(client, org["analyst_a"])
    approved = submit(client, org["analyst_a"])
    decide(client, org["manager_a"], approved["id"], "approved")

    expected = pending["id"] if status == "pending" else approved["id"]
    assert listed_ids(client, org["analyst_a"], status=status) == [expected]


def test_unknown_user_is_rejected(client, org):
    response = client.get("/api/requests", headers={"X-User-Id": "9999"})
    assert response.status_code == 401
