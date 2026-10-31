from __future__ import annotations


def test_workspace_isolation_between_users(make_user):
    alice, bob = make_user("Alice"), make_user("Bob")
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        ws = c.post("/api/v1/workspaces", json={"name": "Alice Private"}, headers=alice["headers"]).json()
        # Bob cannot read, update, list members of, or even confirm the existence of Alice's workspace.
        assert c.get(f"/api/v1/workspaces/{ws['id']}", headers=bob["headers"]).status_code == 404
        assert c.patch(f"/api/v1/workspaces/{ws['id']}", json={"name": "Hacked"}, headers=bob["headers"]).status_code == 404
        assert c.get(f"/api/v1/workspaces/{ws['id']}/members", headers=bob["headers"]).status_code == 404
        listed = c.get("/api/v1/workspaces", headers=bob["headers"]).json()
        assert ws["id"] not in [w["id"] for w in listed]
        # Unauthenticated access is rejected outright.
        assert c.get(f"/api/v1/workspaces/{ws['id']}").status_code == 401


def test_member_management_and_roles(make_user):
    owner, member, outsider = make_user("Owner"), make_user("Member"), make_user("Outsider")
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        ws = c.post("/api/v1/workspaces", json={"name": "Team"}, headers=owner["headers"]).json()["id"]
        r = c.post(f"/api/v1/workspaces/{ws}/members", json={"email": member["email"], "role": "member"}, headers=owner["headers"])
        assert r.status_code == 201
        # A plain member can read but cannot manage.
        assert c.get(f"/api/v1/workspaces/{ws}", headers=member["headers"]).status_code == 200
        assert c.post(f"/api/v1/workspaces/{ws}/members", json={"email": outsider["email"]}, headers=member["headers"]).status_code == 403
        assert c.patch(f"/api/v1/workspaces/{ws}", json={"name": "X"}, headers=member["headers"]).status_code == 403
        # Duplicate add and unknown email.
        assert c.post(f"/api/v1/workspaces/{ws}/members", json={"email": member["email"]}, headers=owner["headers"]).status_code == 409
        assert c.post(f"/api/v1/workspaces/{ws}/members", json={"email": "ghost@example.com"}, headers=owner["headers"]).status_code == 404
        # Owner cannot be removed or demoted.
        assert c.delete(f"/api/v1/workspaces/{ws}/members/{owner['id']}", headers=owner["headers"]).status_code == 403
        assert c.patch(f"/api/v1/workspaces/{ws}/members/{owner['id']}", json={"role": "member"}, headers=owner["headers"]).status_code == 403
        # A member can leave on their own.
        assert c.delete(f"/api/v1/workspaces/{ws}/members/{member['id']}", headers=member["headers"]).status_code == 204
        assert c.get(f"/api/v1/workspaces/{ws}", headers=member["headers"]).status_code == 404
