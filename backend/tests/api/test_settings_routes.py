def test_get_and_patch_settings(logged_in_client):
    s = logged_in_client.get("/api/settings").json()
    assert s["nudge_followup_days"] == 10 and s["claude_job_max_items"] == 8 and "id" not in s
    r = logged_in_client.patch("/api/settings", json={"outreach_profile": "CS junior", "nudge_followup_days": 7})
    assert r.status_code == 200 and r.json()["nudge_followup_days"] == 7 and r.json()["nudge_unsent_days"] == 5


def test_patch_settings_validation(logged_in_client):
    assert logged_in_client.patch("/api/settings", json={"nudge_followup_days": 0}).status_code == 422
    assert logged_in_client.patch("/api/settings", json={"claude_job_max_items": 26}).status_code == 422


def test_settings_expose_discovery_fields(logged_in_client):
    s = logged_in_client.get("/api/settings").json()
    assert s["discovery_terms"] == ["Summer 2027"]
    assert s["discovery_categories"] == ["Software", "AI/ML/Data"]
    assert s["discovery_watchlist_keywords"] == ["intern", "internship", "co-op"]
    assert s["discovery_exclude_keywords"] == ["senior", "staff", "principal", "phd"]
    assert s["discovery_include_keywords"] == [] and s["discovery_locations"] == []
    assert len(s["discovery_list_urls"]) == 2
    assert all(u.startswith("https://raw.githubusercontent.com/") for u in s["discovery_list_urls"])
    assert s["discovery_hide_no_sponsorship"] is False and s["discovery_scan_hours"] == 6
    assert s["last_scan_at"] is None and s["last_scan_error"] is None
    assert "discovery_list_etags" not in s


def test_patch_discovery_settings(logged_in_client):
    r = logged_in_client.patch(
        "/api/settings",
        json={"discovery_locations": [" Remote ", "remote", ""], "discovery_scan_hours": 24},
    )
    assert r.status_code == 200
    assert r.json()["discovery_locations"] == ["Remote"] and r.json()["discovery_scan_hours"] == 24


def test_patch_discovery_settings_validation(logged_in_client):
    r = logged_in_client.patch("/api/settings", json={"discovery_list_urls": ["http://example.com/l.json"]})
    assert r.status_code == 422
    assert logged_in_client.patch("/api/settings", json={"discovery_scan_hours": 0}).status_code == 422
    # The ETag map is server-owned: not settable through the API.
    r = logged_in_client.patch("/api/settings", json={"discovery_list_etags": {"x": "y"}})
    assert r.status_code == 200 and "discovery_list_etags" not in r.json()
