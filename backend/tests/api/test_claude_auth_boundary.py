import pytest

from app.services.claude_token_service import create_token, revoke_token


def test_claude_route_accepts_valid_bearer(client, db_session):
    _, raw = create_token(db_session)
    r = client.get("/api/claude/ping", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_claude_route_rejects_session_cookie(logged_in_client):
    r = logged_in_client.get("/api/claude/ping")
    assert r.status_code == 401 and r.json() == {"detail": "invalid claude token"}


def test_claude_route_rejects_access_token_as_bearer(logged_in_client):
    jwt = logged_in_client.cookies.get("access_token")
    assert jwt
    logged_in_client.cookies.clear()
    r = logged_in_client.get("/api/claude/ping", headers={"Authorization": f"Bearer {jwt}"})
    assert r.status_code == 401


def test_claude_token_rejected_on_cookie_routes(client, db_session):
    _, raw = create_token(db_session)
    for path in ["/api/applications", "/api/contacts", "/api/settings", "/api/settings/claude-tokens", "/api/research-queue"]:
        r = client.get(path, headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 401, path
    client.cookies.set("access_token", raw)
    assert client.get("/api/contacts").status_code == 401


def test_revoked_token_rejected(client, db_session):
    token, raw = create_token(db_session)
    revoke_token(db_session, token.id)
    r = client.get("/api/claude/ping", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 401 and r.json() == {"detail": "invalid claude token"}


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", "Basic xyz", "", "Token abc"])
def test_malformed_authorization_header_rejected(client, db_session, header):
    _, raw = create_token(db_session)
    r = client.get("/api/claude/ping", headers={"Authorization": header})
    assert r.status_code == 401 and r.json() == {"detail": "invalid claude token"}


def test_missing_header_rejected(client):
    assert client.get("/api/claude/ping").status_code == 401


def test_token_management_requires_cookie(client):
    assert client.get("/api/settings/claude-tokens").status_code == 401
    assert client.post("/api/settings/claude-tokens").status_code == 401
    assert client.post("/api/settings/claude-tokens/1/revoke").status_code == 401


def test_token_list_never_contains_plaintext(logged_in_client):
    created = logged_in_client.post("/api/settings/claude-tokens")
    assert created.status_code == 201
    body = created.json()
    assert body["token"].startswith("ct_") and body["token_prefix"] == body["token"][:8]
    listed = logged_in_client.get("/api/settings/claude-tokens").json()
    assert listed and all("token" not in item for item in listed)
    assert body["token"] not in str(listed)


def test_revoke_route(logged_in_client):
    created = logged_in_client.post("/api/settings/claude-tokens").json()
    r = logged_in_client.post(f"/api/settings/claude-tokens/{created['id']}/revoke")
    assert r.status_code == 200 and r.json()["revoked_at"] is not None and "token" not in r.json()
    logged_in_client.cookies.clear()
    assert logged_in_client.get("/api/claude/ping", headers={"Authorization": f"Bearer {created['token']}"}).status_code == 401


def test_revoke_unknown_token_404(logged_in_client):
    r = logged_in_client.post("/api/settings/claude-tokens/999999/revoke")
    assert r.status_code == 404 and r.json() == {"detail": "claude token not found"}
