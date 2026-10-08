def test_add_and_list_queue_items(logged_in_client):
    r = logged_in_client.post(
        "/api/research-queue", json={"kind": "professor_search", "request_text": "5 ML profs at UIUC", "target_count": 5}
    )
    assert r.status_code == 201 and r.json()["target_count"] == 5 and r.json()["state"] == "pending"
    assert [i["id"] for i in logged_in_client.get("/api/research-queue?state=pending").json()] == [r.json()["id"]]
    assert logged_in_client.get("/api/research-queue?state=done").json() == []


def test_add_rejects_company_kind(logged_in_client):
    r = logged_in_client.post("/api/research-queue", json={"kind": "company_contacts", "request_text": "x"})
    assert r.status_code == 422


def test_find_contacts_twice_then_409(logged_in_client):
    app = logged_in_client.post("/api/applications", json={"company": "Stripe", "role_title": "SWE"}).json()
    r = logged_in_client.post(f"/api/research-queue/find-contacts/{app['id']}")
    assert r.status_code == 201 and r.json()["kind"] == "company_contacts" and r.json()["application_id"] == app["id"]
    r = logged_in_client.post(f"/api/research-queue/find-contacts/{app['id']}")
    assert r.status_code == 409 and r.json() == {"detail": "already queued"}


def test_find_contacts_unknown_application(logged_in_client):
    r = logged_in_client.post("/api/research-queue/find-contacts/999999")
    assert r.status_code == 404 and r.json() == {"detail": "application not found"}
