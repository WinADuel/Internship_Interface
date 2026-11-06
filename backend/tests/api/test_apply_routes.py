"""Auto-apply routes: the apply profile, the resume, extension tokens, a
prepared application, the local AI drafts and the extension's own routes."""

import base64
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.api.deps import get_local_model_factory
from app.main import app
from app.models.application import Application
from app.models.posting import Posting, PostingSource, PostingState
from app.services import settings_service
from app.services.apply import tokens
from app.services.apply.llm import LocalModelError
from app.services.discovery.http import DiscoveryFetchError
from app.services.discovery.urls import normalize_url
from tests.services.discovery.fakes import json_result

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "apply"
GH_URL = "https://job-boards.greenhouse.io/discord/jobs/8917177002"
GH_API = "https://boards-api.greenhouse.io/v1/boards/discord/jobs/8917177002?questions=true"
WHY_KEY = "question_39003999002"
INHOUSE_KEY = "question_39116043002"
AUTH_KEY = "question_39004003002"
PDF = b"%PDF-1.4 fake resume"

ROUTES = [
    ("GET", "/api/apply/profile"),
    ("PATCH", "/api/apply/profile"),
    ("PUT", "/api/apply/profile/resume?filename=r.pdf"),
    ("DELETE", "/api/apply/profile/resume"),
    ("GET", "/api/apply/extension-tokens"),
    ("POST", "/api/apply/extension-tokens"),
    ("POST", "/api/apply/extension-tokens/1/revoke"),
    ("GET", "/api/apply/postings/1"),
    ("PUT", "/api/apply/postings/1/answers"),
    ("POST", "/api/apply/postings/1/draft-ai"),
]
EXTENSION_ROUTES = [
    ("GET", "/api/extension/ping"),
    ("POST", "/api/extension/fill"),
    ("POST", "/api/extension/applied"),
]


def make_posting(db, *, url=GH_URL, state=PostingState.SAVED, key="8917177002", source=PostingSource.GREENHOUSE):
    posting = Posting(
        source=source,
        source_key=key,
        company="Discord",
        title="Software Engineering Intern",
        locations=["San Francisco, CA"],
        url=url,
        url_key=normalize_url(url),
        terms=["Summer 2027"],
        state=state,
    )
    db.add(posting)
    db.commit()
    return posting


@pytest.fixture()
def greenhouse(discovery_http):
    discovery_http.add("GET", GH_API, json_result(json.loads((FIXTURES / "greenhouse_job_questions.json").read_text())))
    return discovery_http


def fields_of(body):
    return {f["key"]: f for f in body["fields"]}


def set_profile(client, **fields):
    r = client.patch("/api/apply/profile", json={"fields": fields})
    assert r.status_code == 200, r.text
    return r.json()


# --- auth ---------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_apply_routes_need_a_session(client, method, path):
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_extension_token_is_refused_on_app_routes(client, db_session, method, path):
    _, raw = tokens.create_token(db_session)
    assert client.request(method, path, headers={"Authorization": f"Bearer {raw}"}).status_code == 401


@pytest.mark.parametrize(("method", "path"), EXTENSION_ROUTES)
def test_extension_routes_refuse_cookies_and_claude_tokens(logged_in_client, db_session, method, path):
    from app.services.claude_token_service import create_token

    assert logged_in_client.request(method, path, json={"url": GH_URL}).status_code == 401
    _, claude = create_token(db_session)
    r = logged_in_client.request(method, path, json={"url": GH_URL}, headers={"Authorization": f"Bearer {claude}"})
    assert r.status_code == 401


def test_revoked_extension_token_stops_working(client, db_session):
    token, raw = tokens.create_token(db_session)
    headers = {"Authorization": f"Bearer {raw}"}
    assert client.get("/api/extension/ping", headers=headers).json() == {"ok": True}
    tokens.revoke_token(db_session, token.id)
    assert client.get("/api/extension/ping", headers=headers).status_code == 401


def test_extension_token_lifecycle(logged_in_client):
    created = logged_in_client.post("/api/apply/extension-tokens").json()
    assert created["token"].startswith("ih_") and created["token_prefix"] == created["token"][:8]
    listed = logged_in_client.get("/api/apply/extension-tokens").json()
    assert [t["id"] for t in listed] == [created["id"]] and "token" not in listed[0]
    revoked = logged_in_client.post(f"/api/apply/extension-tokens/{created['id']}/revoke").json()
    assert revoked["revoked_at"] is not None
    assert logged_in_client.post("/api/apply/extension-tokens/999999/revoke").status_code == 404


# --- profile and resume -------------------------------------------------------------


def test_profile_starts_blank_and_saves(logged_in_client):
    body = logged_in_client.get("/api/apply/profile").json()
    assert body["fields"]["first_name"] == "" and body["saved_answers"] == [] and body["resume_filename"] is None
    body = set_profile(logged_in_client, first_name=" Dana ", work_authorized="yes", gender="decline")
    assert body["fields"]["first_name"] == "Dana" and body["fields"]["work_authorized"] == "yes"
    r = logged_in_client.patch(
        "/api/apply/profile",
        json={"saved_answers": [{"question": "Why us?", "answer": "Because."}], "llm_url": "http://192.168.1.20:11434/", "llm_model": "qwen3:14b"},
    )
    body = r.json()
    assert body["fields"]["first_name"] == "Dana"  # untouched
    assert body["saved_answers"] == [{"question": "Why us?", "answer": "Because."}]
    assert (body["llm_url"], body["llm_model"]) == ("http://192.168.1.20:11434", "qwen3:14b")


@pytest.mark.parametrize(
    "body",
    [
        {"fields": {"work_authorized": "maybe"}},
        {"fields": {"unknown_field": "x"}},
        {"llm_url": "ftp://box"},
        {"saved_answers": [{"question": "", "answer": "x"}]},
    ],
)
def test_profile_rejects_bad_input(logged_in_client, body):
    assert logged_in_client.patch("/api/apply/profile", json=body).status_code == 422


def test_resume_upload_replace_and_delete(logged_in_client):
    r = logged_in_client.put(
        "/api/apply/profile/resume?filename=../My Resume.pdf", content=PDF, headers={"Content-Type": "application/pdf"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["resume_filename"] == "My Resume.pdf" and r.json()["resume_uploaded_at"]
    r = logged_in_client.put(
        "/api/apply/profile/resume?filename=cv",
        content=b"PK docx",
        headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    )
    assert r.json()["resume_filename"] == "cv.docx"
    assert logged_in_client.delete("/api/apply/profile/resume").json()["resume_filename"] is None


@pytest.mark.parametrize(
    ("content", "content_type", "status"),
    [
        (b"hello", "text/plain", 422),
        (b"not a pdf", "application/pdf", 422),
        (b"", "application/pdf", 422),
        (b"%PDF" + b"x" * (5 * 1024 * 1024), "application/pdf", 413),
    ],
    # Named ids: the 5 MB body would otherwise become the test's name, and that one 5 MB
    # line in `pytest -v` output stalls the GitHub Actions log until the job times out.
    ids=["plain-text", "not-a-pdf", "empty", "too-large"],
)
def test_resume_upload_rejects_bad_files(logged_in_client, content, content_type, status):
    r = logged_in_client.put(
        "/api/apply/profile/resume?filename=r.pdf", content=content, headers={"Content-Type": content_type}
    )
    assert r.status_code == status


# --- prepared applications ----------------------------------------------------------


def test_prepare_reads_the_form_once_and_prefills(logged_in_client, db_session, greenhouse):
    posting = make_posting(db_session)
    set_profile(logged_in_client, first_name="Dana", last_name="Lee", email="d@example.com", work_authorized="yes")
    logged_in_client.put("/api/apply/profile/resume?filename=r.pdf", content=PDF, headers={"Content-Type": "application/pdf"})

    body = logged_in_client.get(f"/api/apply/postings/{posting.id}").json()
    assert body["apply_url"] == GH_URL and body["ats"] == "greenhouse" and body["posting_state"] == "saved"
    fields = fields_of(body)
    assert fields["first_name"]["value"] == "Dana" and fields["first_name"]["source"] == "profile"
    assert fields[AUTH_KEY]["value"] == "Yes"
    assert fields["resume"]["value"] == "r.pdf"
    assert fields[WHY_KEY]["value"] == "" and fields[WHY_KEY]["source"] == ""
    assert fields["4033069002"]["value"] == []  # multiselect: empty list
    assert body["llm_ready"] is False

    logged_in_client.get(f"/api/apply/postings/{posting.id}")
    assert len(greenhouse.calls) == 1  # cached


def test_answers_save_remember_and_survive_a_refresh(logged_in_client, db_session, greenhouse):
    posting = make_posting(db_session)
    logged_in_client.get(f"/api/apply/postings/{posting.id}")
    r = logged_in_client.put(
        f"/api/apply/postings/{posting.id}/answers",
        json={"answers": {WHY_KEY: {"value": "  I use Discord daily.  ", "remember": True}, "4033069002": {"value": ["East Asian"]}}},
    )
    assert r.status_code == 200, r.text
    fields = fields_of(r.json())
    assert fields[WHY_KEY]["value"] == "I use Discord daily."
    assert fields[WHY_KEY]["source"] == "you"
    saved = logged_in_client.get("/api/apply/profile").json()["saved_answers"]
    assert saved == [{"question": "Why do you want to work at Discord?", "answer": "I use Discord daily."}]

    # A refresh re-reads the form but keeps the owner's answers.
    set_profile(logged_in_client, first_name="Dana")
    body = logged_in_client.get(f"/api/apply/postings/{posting.id}?refresh=true").json()
    fields = fields_of(body)
    assert fields[WHY_KEY]["value"] == "I use Discord daily." and fields["first_name"]["value"] == "Dana"
    assert len(greenhouse.calls) == 2

    # Clearing a value removes it; an unknown key is refused.
    body = logged_in_client.put(f"/api/apply/postings/{posting.id}/answers", json={"answers": {WHY_KEY: {"value": ""}}}).json()
    assert fields_of(body)[WHY_KEY]["value"] == ""
    r = logged_in_client.put(f"/api/apply/postings/{posting.id}/answers", json={"answers": {"nope": {"value": "x"}}})
    assert r.status_code == 422


def test_prepare_errors(logged_in_client, db_session, discovery_http):
    assert logged_in_client.get("/api/apply/postings/999999").status_code == 404
    other = make_posting(db_session, url="https://careers.example.com/jobs/1", key="x", source=PostingSource.PASTED)
    r = logged_in_client.get(f"/api/apply/postings/{other.id}")
    assert r.status_code == 422 and "Greenhouse, Lever and Ashby" in r.json()["detail"]
    posting = make_posting(db_session)
    discovery_http.add("GET", GH_API, DiscoveryFetchError("gone", status=404))
    r = logged_in_client.get(f"/api/apply/postings/{posting.id}")
    assert r.status_code == 422 and "no longer exists" in r.json()["detail"]
    assert logged_in_client.put(f"/api/apply/postings/{posting.id}/answers", json={"answers": {}}).status_code == 404


class FakeModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture()
def fake_model():
    holder = {}

    def factory(url, model):
        holder["args"] = (url, model)
        return holder["model"]

    app.dependency_overrides[get_local_model_factory] = lambda: factory
    yield holder
    app.dependency_overrides.pop(get_local_model_factory, None)


def test_draft_with_local_ai(logged_in_client, db_session, greenhouse, fake_model):
    posting = make_posting(db_session)
    logged_in_client.get(f"/api/apply/postings/{posting.id}")
    r = logged_in_client.post(f"/api/apply/postings/{posting.id}/draft-ai", json={})
    assert r.status_code == 422 and "Settings" in r.json()["detail"]

    settings_service.get_settings(db_session).outreach_profile = "Computer Engineering student at UW; built a MicroMouse."
    db_session.commit()
    logged_in_client.patch("/api/apply/profile", json={"llm_url": "http://10.0.0.5:11434", "llm_model": "qwen3:14b"})
    fake_model["model"] = FakeModel(["I love how Discord brings people together.", "NEEDS YOU"])
    body = logged_in_client.post(f"/api/apply/postings/{posting.id}/draft-ai", json={}).json()
    assert fake_model["args"] == ("http://10.0.0.5:11434", "qwen3:14b")
    assert body["drafted"] == [WHY_KEY] and body["failed"] == [INHOUSE_KEY] and body["error"] is None
    fields = fields_of(body["draft"])
    assert fields[WHY_KEY] == fields[WHY_KEY] | {"value": "I love how Discord brings people together.", "source": "ai"}
    assert fields[INHOUSE_KEY]["value"] == ""
    prompt = fake_model["model"].prompts[0]
    assert "Discord" in prompt and "MicroMouse" in prompt and "Why do you want to work at Discord?" in prompt

    # Drafted answers aren't redone; an unreachable model is reported once.
    fake_model["model"] = FakeModel([LocalModelError("couldn't reach the local model (ConnectError)")])
    body = logged_in_client.post(f"/api/apply/postings/{posting.id}/draft-ai", json={}).json()
    assert body["drafted"] == [] and body["failed"] == [INHOUSE_KEY] and "couldn't reach" in body["error"]
    assert fields_of(body["draft"])[WHY_KEY]["source"] == "ai"


# --- the extension --------------------------------------------------------------------


@pytest.fixture()
def ext_headers(db_session):
    _, raw = tokens.create_token(db_session)
    return {"Authorization": f"Bearer {raw}"}


def test_extension_fill_for_a_saved_posting(client, db_session, greenhouse, ext_headers, logged_in_client):
    posting = make_posting(db_session)
    set_profile(logged_in_client, first_name="Dana", email="d@example.com")
    logged_in_client.put("/api/apply/profile/resume?filename=r.pdf", content=PDF, headers={"Content-Type": "application/pdf"})
    logged_in_client.cookies.clear()

    r = client.post("/api/extension/fill", json={"url": GH_URL + "?gh_src=abc#app"}, headers=ext_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["posting"] == {"id": posting.id, "company": "Discord", "title": "Software Engineering Intern", "state": "saved"}
    assert body["ats"] == "greenhouse" and body["message"] is None
    fields = fields_of(body)
    assert fields["first_name"]["value"] == "Dana"
    assert body["profile"]["email"] == "d@example.com"
    assert base64.b64decode(body["resume"]["data_base64"]) == PDF
    assert body["resume"]["content_type"] == "application/pdf"


def test_extension_fill_for_an_unsaved_job_gives_the_profile(client, db_session, ext_headers):
    r = client.post("/api/extension/fill", json={"url": "https://jobs.lever.co/acme/6ed76ce8-4156-4b60-b120-403538bd66cd/apply"}, headers=ext_headers)
    body = r.json()
    assert body["posting"] is None and body["fields"] == [] and "isn't saved" in body["message"]
    assert "first_name" in body["profile"] and body["resume"] is None


def test_extension_fill_finds_lever_and_ashby_postings_from_their_apply_pages(client, db_session, ext_headers, discovery_http):
    lever = make_posting(
        db_session, url="https://jobs.lever.co/palantir/6ed76ce8-4156-4b60-b120-403538bd66cd",
        key="6ed76ce8-4156-4b60-b120-403538bd66cd", source=PostingSource.LEVER,
    )
    discovery_http.add("PAGE", lever.url + "/apply", DiscoveryFetchError("down"))
    body = client.post("/api/extension/fill", json={"url": lever.url + "/apply"}, headers=ext_headers).json()
    assert body["posting"]["id"] == lever.id
    assert body["fields"] == [] and "Couldn't read" in body["message"]  # the form read failed: profile only


def test_extension_marks_the_posting_applied_once(client, db_session, ext_headers):
    posting = make_posting(db_session)
    r = client.post("/api/extension/applied", json={"url": GH_URL}, headers=ext_headers).json()
    assert r["status"] == "applied" and r["posting_id"] == posting.id
    db_session.refresh(posting)
    assert posting.state is PostingState.APPLIED
    application = db_session.scalars(select(Application).where(Application.id == r["application_id"])).one()
    assert (application.company, application.status.value, application.job_link) == ("Discord", "applied", GH_URL)
    again = client.post("/api/extension/applied", json={"url": GH_URL}, headers=ext_headers).json()
    assert again == {"status": "already_applied", "posting_id": posting.id, "application_id": application.id}
    other = client.post("/api/extension/applied", json={"url": "https://jobs.example.com/x"}, headers=ext_headers).json()
    assert other["status"] == "not_saved"


def test_extension_leaves_a_dismissed_posting_alone(client, db_session, ext_headers):
    posting = make_posting(db_session, state=PostingState.DISMISSED)
    r = client.post("/api/extension/applied", json={"url": GH_URL}, headers=ext_headers).json()
    assert r["status"] == "not_saved"
    db_session.refresh(posting)
    assert posting.state is PostingState.DISMISSED
