import pytest

ROUTES = [
    ("GET", "/api/stories"),
    ("POST", "/api/stories"),
    ("PATCH", "/api/stories/1"),
    ("DELETE", "/api/stories/1"),
]


def test_routes_list_is_complete():
    # The auth and Claude-token boundary tests walk ROUTES; keep it complete.
    from app.api.stories import router

    served = {
        (method, route.path.replace("{story_id}", "1"))
        for route in router.routes
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    assert served == set(ROUTES)


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_requires_a_session(client, method, path):
    r = client.request(method, path)
    assert r.status_code == 401 and r.json() == {"detail": "not authenticated"}


def _story(client, **fields) -> dict:
    r = client.post("/api/stories", json={"title": "Led a team", **fields})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_list_update_archive_delete(logged_in_client):
    created = _story(
        logged_in_client, situation="S", task="T", action="A", result="R", tags=[" Leadership ", "leadership", "Conflict"]
    )
    assert set(created) == {
        "id", "title", "situation", "task", "action", "result", "tags", "archived", "created_at", "updated_at",
    }
    assert created["tags"] == ["leadership", "conflict"] and created["archived"] is False
    other = _story(logged_in_client, title="Another")

    assert [s["id"] for s in logged_in_client.get("/api/stories").json()] == [other["id"], created["id"]]
    tagged = logged_in_client.get("/api/stories", params={"tag": "Conflict"}).json()
    assert [s["id"] for s in tagged] == [created["id"]]

    r = logged_in_client.patch(f"/api/stories/{created['id']}", json={"archived": True, "result": "Shipped"})
    assert r.status_code == 200 and r.json()["archived"] is True and r.json()["result"] == "Shipped"
    assert [s["id"] for s in logged_in_client.get("/api/stories").json()] == [other["id"]]
    everything = logged_in_client.get("/api/stories", params={"include_archived": "true"}).json()
    assert {s["id"] for s in everything} == {created["id"], other["id"]}

    assert logged_in_client.delete(f"/api/stories/{created['id']}").status_code == 204
    assert logged_in_client.patch(f"/api/stories/{created['id']}", json={"title": "x"}).status_code == 404
    r = logged_in_client.delete(f"/api/stories/{created['id']}")
    assert r.status_code == 404 and r.json() == {"detail": "story not found"}


@pytest.mark.parametrize(
    "fields",
    [
        {"title": ""},
        {"title": "x" * 201},
        {"situation": "x" * 5_001},
        {"result": "x" * 5_001},
        {"tags": [f"t{i}" for i in range(16)]},
        {"tags": ["x" * 41]},
    ],
)
def test_story_validation_caps(logged_in_client, fields):
    assert logged_in_client.post("/api/stories", json={"title": "ok", **fields}).status_code == 422


def test_patch_rejects_null_title(logged_in_client):
    story = _story(logged_in_client)
    assert logged_in_client.patch(f"/api/stories/{story['id']}", json={"title": None}).status_code == 422
