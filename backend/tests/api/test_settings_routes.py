def test_get_and_patch_settings(logged_in_client):
    s = logged_in_client.get("/api/settings").json()
    assert s["nudge_followup_days"] == 10 and s["claude_job_max_items"] == 8 and "id" not in s
    r = logged_in_client.patch("/api/settings", json={"outreach_profile": "CS junior", "nudge_followup_days": 7})
    assert r.status_code == 200 and r.json()["nudge_followup_days"] == 7 and r.json()["nudge_unsent_days"] == 5


def test_patch_settings_validation(logged_in_client):
    assert logged_in_client.patch("/api/settings", json={"nudge_followup_days": 0}).status_code == 422
    assert logged_in_client.patch("/api/settings", json={"claude_job_max_items": 26}).status_code == 422
