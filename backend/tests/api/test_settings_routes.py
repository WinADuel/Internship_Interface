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


RANKING_LISTS = (
    "ranking_role_keywords",
    "ranking_skill_keywords",
    "ranking_preferred_locations",
    "ranking_preferred_companies",
    "ranking_avoid_companies",
    "ranking_dealbreaker_keywords",
)


def test_settings_expose_ranking_fields(logged_in_client):
    s = logged_in_client.get("/api/settings").json()
    assert all(s[name] == [] for name in RANKING_LISTS)
    assert s["ranking_claude_daily_limit"] == 40 and s["ranking_updated_at"] is None


def test_patch_ranking_settings_rescores_and_stamps(logged_in_client):
    r = logged_in_client.patch(
        "/api/settings",
        json={"ranking_role_keywords": [" machine learning ", "Machine Learning", ""], "ranking_claude_daily_limit": 0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ranking_role_keywords"] == ["machine learning"]
    assert body["ranking_claude_daily_limit"] == 0 and body["ranking_updated_at"] is not None


def test_patch_ranking_settings_validation(logged_in_client):
    for payload in (
        {"ranking_role_keywords": ["x" * 61]},
        {"ranking_skill_keywords": [f"k{i}" for i in range(31)]},
        {"ranking_avoid_companies": None},
        {"ranking_claude_daily_limit": -1},
        {"ranking_claude_daily_limit": 151},
        {"ranking_claude_daily_limit": None},
    ):
        assert logged_in_client.patch("/api/settings", json=payload).status_code == 422, payload
    # ranking_updated_at is server-owned.
    r = logged_in_client.patch("/api/settings", json={"ranking_updated_at": "2020-01-01T00:00:00Z"})
    assert r.status_code == 200 and r.json()["ranking_updated_at"] is None
