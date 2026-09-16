"""Signing in proves who you are; a grant is what opens a tool."""

from __future__ import annotations

from conftest import auth
from test_api import submit

from app.entitlements import entitlement_for
from app.models import AppRole, AppSlug


def test_home_lists_only_the_tools_the_caller_holds(client, org, session):
    analyst = client.get("/api/me/apps", headers=auth(org["analyst_a"])).json()
    assert [app["slug"] for app in analyst] == ["refunds"]
    assert analyst[0]["app_role"] == AppRole.contributor.value

    # Platform admins hold every tool without needing a row per person.
    admin = client.get("/api/me/apps", headers=auth(org["admin"])).json()
    assert [app["slug"] for app in admin] == [slug.value for slug in AppSlug]
    assert {app["app_role"] for app in admin} == {AppRole.admin.value}

    session.delete(entitlement_for(session, org["analyst_a"], AppSlug.refunds))
    session.commit()
    assert client.get("/api/me/apps", headers=auth(org["analyst_a"])).json() == []


def test_losing_the_grant_closes_the_tool_not_just_the_tile(client, org, session):
    headers = auth(org["analyst_a"])
    assert client.get("/api/refunds/requests", headers=headers).status_code == 200

    session.delete(entitlement_for(session, org["analyst_a"], AppSlug.refunds))
    session.commit()

    # 404, not 403: a refusal that distinguishes "no access" from "no such tool"
    # tells an outsider what exists.
    assert client.get("/api/refunds/requests", headers=headers).status_code == 404
    assert client.get("/api/refunds/config", headers=headers).status_code == 404


def test_a_viewer_can_read_the_queue_but_not_submit(client, org, session):
    grant = entitlement_for(session, org["analyst_a"], AppSlug.refunds)
    grant.app_role = AppRole.viewer
    session.commit()

    headers = auth(org["analyst_a"])
    assert client.get("/api/refunds/requests", headers=headers).status_code == 200
    blocked = client.post(
        "/api/refunds/requests",
        json={
            "customer_id": "CUS-1",
            "customer_name": "Test Customer",
            "order_id": "ORD-1",
            "reason": "duplicate_charge",
            "amount_cents": 5000,
            "note": "",
        },
        headers=headers,
    )
    assert blocked.status_code == 404


def test_the_refund_hierarchy_still_applies_on_top_of_the_grant(client, org, session):
    """A grant opens the tool; it does not widen who you may decide for."""
    request = submit(client, org["analyst_b"])
    # Manager A holds refunds at reviewer level but Analyst B is not their report.
    seen = client.get(f"/api/refunds/requests/{request['id']}", headers=auth(org["manager_a"]))
    assert seen.status_code == 404
