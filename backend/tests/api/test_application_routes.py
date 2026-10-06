import pytest


def _create(client, **overrides):
    body = {"company": "A", "role_title": "R", **overrides}
    response = client.post("/api/applications", json=body)
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/applications"),
        ("post", "/api/applications"),
        ("get", "/api/applications/1"),
        ("patch", "/api/applications/1"),
        ("post", "/api/applications/1/status"),
        ("post", "/api/applications/1/archive"),
        ("get", "/api/applications/1/history"),
        ("get", "/api/applications/activity"),
    ],
)
def test_all_routes_require_auth(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


def test_list_applications_requires_auth(client):
    response = client.get("/api/applications")
    assert response.status_code == 401


def test_create_and_list_application(logged_in_client):
    create_resp = logged_in_client.post(
        "/api/applications", json={"company": "Stripe", "role_title": "SWE Intern"}
    )
    assert create_resp.status_code == 201
    list_resp = logged_in_client.get("/api/applications")
    assert any(a["company"] == "Stripe" for a in list_resp.json())


def test_get_application(logged_in_client):
    created = _create(logged_in_client, company="Stripe")
    response = logged_in_client.get(f"/api/applications/{created['id']}")
    assert response.status_code == 200
    assert response.json()["company"] == "Stripe"


def test_get_missing_application_returns_404(logged_in_client):
    response = logged_in_client.get("/api/applications/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "application not found"}


def test_patch_updates_fields(logged_in_client):
    created = _create(logged_in_client)
    response = logged_in_client.patch(
        f"/api/applications/{created['id']}", json={"notes": "hello", "company": "B"}
    )
    assert response.status_code == 200
    assert response.json()["notes"] == "hello"
    assert response.json()["company"] == "B"


def test_patch_missing_application_returns_404(logged_in_client):
    response = logged_in_client.patch("/api/applications/999", json={"notes": "x"})
    assert response.status_code == 404
    assert response.json() == {"detail": "application not found"}


@pytest.mark.parametrize("field", ["company", "role_title", "status", "priority"])
def test_patch_rejects_null_for_non_nullable_field(logged_in_client, field):
    created = _create(logged_in_client)
    response = logged_in_client.patch(f"/api/applications/{created['id']}", json={field: None})
    assert response.status_code == 422


def test_patch_allows_null_for_nullable_field(logged_in_client):
    created = _create(logged_in_client, notes="x")
    response = logged_in_client.patch(f"/api/applications/{created['id']}", json={"notes": None})
    assert response.status_code == 200
    assert response.json()["notes"] is None


def test_status_change_updates_status_and_history(logged_in_client):
    created = _create(logged_in_client)
    response = logged_in_client.post(
        f"/api/applications/{created['id']}/status", json={"new_status": "applied"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    history = logged_in_client.get(f"/api/applications/{created['id']}/history").json()
    assert [h["new_status"] for h in history] == ["wishlist", "applied"]
    assert history[0]["old_status"] is None
    assert history[1]["old_status"] == "wishlist"


def test_status_change_rejects_invalid_value(logged_in_client):
    created = _create(logged_in_client)
    response = logged_in_client.post(
        f"/api/applications/{created['id']}/status", json={"new_status": "not-a-status"}
    )
    assert response.status_code == 422


def test_status_change_missing_application_returns_404(logged_in_client):
    response = logged_in_client.post("/api/applications/999/status", json={"new_status": "applied"})
    assert response.status_code == 404
    assert response.json() == {"detail": "application not found"}


def test_archived_application_excluded_from_default_list(logged_in_client):
    created = _create(logged_in_client)
    archive = logged_in_client.post(f"/api/applications/{created['id']}/archive")
    assert archive.status_code == 200
    assert archive.json()["archived"] is True
    response = logged_in_client.get("/api/applications")
    assert created["id"] not in [a["id"] for a in response.json()]
    included = logged_in_client.get("/api/applications?include_archived=true")
    assert created["id"] in [a["id"] for a in included.json()]


def test_archive_missing_application_returns_404(logged_in_client):
    response = logged_in_client.post("/api/applications/999/archive")
    assert response.status_code == 404


def test_history_missing_application_returns_404(logged_in_client):
    response = logged_in_client.get("/api/applications/999/history")
    assert response.status_code == 404
    assert response.json() == {"detail": "application not found"}


def test_activity_feed_is_not_parsed_as_id_and_respects_limit(logged_in_client):
    first = _create(logged_in_client, company="First")
    _create(logged_in_client, company="Second")
    logged_in_client.post(f"/api/applications/{first['id']}/status", json={"new_status": "applied"})
    response = logged_in_client.get("/api/applications/activity?limit=2")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 2
    assert entries[0]["company"] == "First"
    assert entries[0]["new_status"] == "applied"
    assert entries[0]["old_status"] == "wishlist"
    assert entries[1]["company"] == "Second"
