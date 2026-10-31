from __future__ import annotations

import io
import json

import pytest

from app.cli import make_admin
from app.core.exceptions import ProviderError
from tests.conftest import personal_workspace, run_worker

REFUND = b"Refund policy: customers may request a refund within 14 days of purchase."


def upload(client, headers, ws, name, data):
    return client.post(f"/api/v1/workspaces/{ws}/documents", headers=headers,
                       files=[("files", (name, io.BytesIO(data), "text/plain"))])


def chat(client, headers, ws, q):
    return client.post(f"/api/v1/workspaces/{ws}/chat/stream", headers=headers, json={"message": q})


def done_id(resp):
    for frame in resp.text.strip().split("\n\n"):
        lines = frame.split("\n")
        if lines[0] == "event: done":
            return json.loads(lines[1][6:])["message_id"]
    raise AssertionError(resp.text)


def analytics(client, headers, ws):
    r = client.get(f"/api/v1/workspaces/{ws}/analytics", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_empty_workspace_reports_zeros_and_nulls_not_fake_numbers(client, make_user, providers):
    u = make_user("Empty")
    ws = personal_workspace(client, u["headers"])
    a = analytics(client, u["headers"], ws)
    assert a["documents"]["total"] == 0 and a["documents"]["indexed_chunks"] == 0 and a["documents"]["recent_failures"] == []
    assert a["usage"]["queries_30d"] == 0 and a["usage"]["conversations_total"] == 0
    assert len(a["usage"]["daily_queries"]) == 14 and all(d["queries"] == 0 for d in a["usage"]["daily_queries"])
    assert a["latency_ms"]["samples"] == 0 and a["latency_ms"]["p95_total"] is None and a["latency_ms"]["avg_rerank"] is None
    assert a["reliability"]["provider_error_rate"] is None and a["feedback"]["satisfaction"] is None
    assert a["evaluation"] == {"runs": 0, "latest": None}


def test_analytics_reflect_real_usage_failures_feedback_and_latency(client, make_user, providers):
    u = make_user("Busy")
    ws = personal_workspace(client, u["headers"])
    assert upload(client, u["headers"], ws, "refunds.txt", REFUND).json()["results"][0]["accepted"]
    upload(client, u["headers"], ws, "broken.pdf", b"%PDF-1.4\n" + b"junk" * 40)
    assert run_worker() == ["ready", "failed"]

    m1 = done_id(chat(client, u["headers"], ws, "What is the refund policy?"))
    chat(client, u["headers"], ws, "refund within 14 days?")
    providers.reranker.fail_with = ProviderError("cohere", "down", retryable=False)
    chat(client, u["headers"], ws, "refund again")
    providers.reranker.fail_with = None
    client.put(f"/api/v1/workspaces/{ws}/messages/{m1}/feedback", json={"rating": 1}, headers=u["headers"])

    a = analytics(client, u["headers"], ws)
    assert a["documents"]["by_status"]["ready"] == 1 and a["documents"]["by_status"]["failed"] == 1
    assert a["documents"]["indexed_chunks"] == 1
    fail = a["documents"]["recent_failures"][0]
    assert fail["filename"] == "broken.pdf" and fail["error_summary"]
    assert a["usage"]["queries_30d"] == 3 and a["usage"]["queries_7d"] == 3 and a["usage"]["active_users_30d"] == 1
    assert a["usage"]["daily_queries"][-1]["queries"] == 3 and a["usage"]["conversations_total"] == 3
    lat = a["latency_ms"]
    assert lat["samples"] == 2 and lat["p50_total"] is not None and lat["p95_total"] >= lat["p50_total"] > 0
    assert lat["avg_retrieval"] is not None and lat["avg_rerank"] is not None and lat["avg_generation"] is not None
    rel = a["reliability"]
    assert rel["ok"] == 2 and rel["errors"] == 1 and rel["provider_errors"] == 1
    assert rel["provider_error_rate"] == pytest.approx(1 / 3, abs=1e-3) and rel["by_provider"] == {"cohere": 1}
    assert a["feedback"] == {"up": 1, "down": 0, "with_comment": 0, "satisfaction": 1.0}


def test_analytics_are_scoped_to_the_workspace(client, make_user, providers):
    a_user, b_user = make_user("A"), make_user("B")
    ws_a, ws_b = personal_workspace(client, a_user["headers"]), personal_workspace(client, b_user["headers"])
    upload(client, a_user["headers"], ws_a, "a.txt", REFUND)
    run_worker()
    chat(client, a_user["headers"], ws_a, "refund policy")
    assert analytics(client, a_user["headers"], ws_a)["usage"]["queries_30d"] == 1
    assert analytics(client, b_user["headers"], ws_b)["usage"]["queries_30d"] == 0
    assert analytics(client, b_user["headers"], ws_b)["documents"]["total"] == 0


def test_analytics_authorization(client, make_user, providers, db):
    owner, member, outsider, admin = make_user("Owner"), make_user("Member"), make_user("Out"), make_user("Root")
    ws = personal_workspace(client, owner["headers"])
    client.post(f"/api/v1/workspaces/{ws}/members", json={"email": member["email"]}, headers=owner["headers"])
    url = f"/api/v1/workspaces/{ws}/analytics"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=member["headers"]).status_code == 403  # plain members cannot see analytics
    assert client.get(url, headers=outsider["headers"]).status_code == 404  # non-members cannot confirm it exists
    assert client.get(url, headers=owner["headers"]).status_code == 200
    # A workspace admin (promoted by the owner) can.
    client.patch(f"/api/v1/workspaces/{ws}/members/{member['id']}", json={"role": "admin"}, headers=owner["headers"])
    assert client.get(url, headers=member["headers"]).status_code == 200
    # Global admins may read aggregates for any workspace; unknown workspaces are 404.
    make_admin(admin["email"])
    assert client.get(url, headers=admin["headers"]).status_code == 200
    assert client.get("/api/v1/workspaces/00000000-0000-0000-0000-000000000000/analytics", headers=admin["headers"]).status_code == 404
    # ...but a global admin still cannot read workspace content.
    assert client.get(f"/api/v1/workspaces/{ws}/documents", headers=admin["headers"]).status_code == 404


def test_admin_endpoints_require_global_admin_role(client, make_user, providers):
    user, admin = make_user("Plain"), make_user("Root")
    for path in ("/api/v1/admin/overview", "/api/v1/admin/audit-events"):
        assert client.get(path).status_code == 401
        r = client.get(path, headers=user["headers"])
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    make_admin(admin["email"])
    ov = client.get("/api/v1/admin/overview", headers=admin["headers"]).json()
    assert ov["users"] == 2 and ov["workspaces"] == 2 and ov["queries_30d"] == 0 and ov["error_rate_30d"] is None
    assert set(ov) == {"window_days", "users", "workspaces", "documents", "queries_30d", "error_rate_30d"}  # counts only


def test_audit_events_record_important_actions(client, make_user, providers):
    owner, admin = make_user("Owner"), make_user("Root")
    ws = personal_workspace(client, owner["headers"])
    upload(client, owner["headers"], ws, "a.txt", REFUND)
    run_worker()
    doc_id = client.get(f"/api/v1/workspaces/{ws}/documents", headers=owner["headers"]).json()["items"][0]["id"]
    client.delete(f"/api/v1/workspaces/{ws}/documents/{doc_id}", headers=owner["headers"])
    res = client.get(f"/api/v1/workspaces/{ws}/audit-events", headers=owner["headers"]).json()
    actions = [e["action"] for e in res["items"]]
    assert {"workspace.create", "document.upload", "document.delete"} <= set(actions)
    assert actions.index("document.delete") < actions.index("document.upload")  # newest first
    deleted = next(e for e in res["items"] if e["action"] == "document.delete")
    assert deleted["actor_email"] == owner["email"] and deleted["details"] == {"filename": "a.txt"}
    only = client.get(f"/api/v1/workspaces/{ws}/audit-events?action=document.upload", headers=owner["headers"]).json()
    assert only["total"] == 1
    # Platform-wide log includes the promotion done through the CLI.
    make_admin(admin["email"])
    glob = client.get("/api/v1/admin/audit-events?action=user.promote_admin", headers=admin["headers"]).json()
    assert glob["total"] == 1 and glob["items"][0]["target_type"] == "user"
    # A user from another workspace cannot read this workspace's log (404: existence is not revealed).
    other = make_user("Other")
    assert client.get(f"/api/v1/workspaces/{ws}/audit-events", headers=other["headers"]).status_code == 404
