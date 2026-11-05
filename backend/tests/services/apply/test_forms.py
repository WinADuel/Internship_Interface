"""Reading Greenhouse, Lever and Ashby application forms. The fixtures in
tests/fixtures/apply/ were recorded from live postings on 2026-11-05
(Discord on Greenhouse, Palantir on Lever, Ramp on Ashby), trimmed."""

import json
from pathlib import Path

import pytest

from app.models.watch_company import WatchAts
from app.services.apply import forms
from app.services.discovery.http import DiscoveryFetchError
from tests.services.discovery.fakes import FakeDiscoveryHttp, json_result, page_result

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "apply"
GH_URL = "https://job-boards.greenhouse.io/discord/jobs/8917177002"
GH_API = "https://boards-api.greenhouse.io/v1/boards/discord/jobs/8917177002?questions=true"
LEVER_ID = "6ed76ce8-4156-4b60-b120-403538bd66cd"
LEVER_URL = f"https://jobs.lever.co/palantir/{LEVER_ID}"
ASHBY_ID = "34413f8d-26bf-4bbc-8ade-eb309a0e2245"
ASHBY_URL = f"https://jobs.ashbyhq.com/ramp/{ASHBY_ID}"


def fixture_json(name: str):
    return json.loads((FIXTURES / name).read_text())


def by_key(read: forms.ReadForm) -> dict[str, forms.FormField]:
    return {f.key: f for f in read.fields}


def test_greenhouse_questions_become_fields():
    http = FakeDiscoveryHttp({("GET", GH_API): json_result(fixture_json("greenhouse_job_questions.json"))})
    read = forms.read_form(http, GH_URL)
    assert read.ats is WatchAts.GREENHOUSE
    assert read.apply_url == GH_URL
    fields = by_key(read)
    assert fields["first_name"].kind == "text" and fields["first_name"].required
    assert fields["resume"].kind == "file"
    # "Enter manually" alternatives of file questions are dropped.
    assert "resume_text" not in fields and "cover_letter_text" not in fields
    why = fields["question_39003999002"]
    assert (why.kind, why.label, why.required) == ("textarea", "Why do you want to work at Discord?", True)
    auth = fields["question_39004003002"]
    assert auth.kind == "select" and [o["label"] for o in auth.options] == ["Yes", "No"]
    assert fields["location"].label == "Location"
    # Hidden latitude/longitude are not fields.
    assert "latitude" not in fields
    gender = fields["4033064002"]
    assert gender.section == "demographic" and gender.kind == "select"
    assert "I don't wish to answer" in [o["label"] for o in gender.options]
    assert fields["4033069002"].kind == "multiselect"


def test_greenhouse_embed_link_reads_the_same_job_and_applies_on_the_hosted_form():
    http = FakeDiscoveryHttp({("GET", GH_API): json_result(fixture_json("greenhouse_job_questions.json"))})
    read = forms.read_form(http, "https://boards.greenhouse.io/embed/job_app?for=discord&token=8917177002")
    assert read.apply_url == GH_URL


def test_lever_apply_page_becomes_fields():
    apply_url = LEVER_URL + "/apply"
    page = (FIXTURES / "lever_apply_page.html").read_text()
    http = FakeDiscoveryHttp({("PAGE", apply_url): page_result(page, url=apply_url)})
    read = forms.read_form(http, LEVER_URL)
    assert read.ats is WatchAts.LEVER and read.apply_url == apply_url
    fields = by_key(read)
    assert fields["name"].required and fields["email"].required and not fields["phone"].required
    assert fields["urls[LinkedIn]"].label == "LinkedIn URL"
    assert fields["resume"].kind == "file"
    auth = next(f for f in read.fields if f.label.startswith("Are you legally authorized"))
    assert auth.kind == "select" and auth.required and auth.key.endswith("[field0]")
    sponsor = next(f for f in read.fields if "sponsorship" in f.label)
    assert sponsor.key == auth.key.replace("field0", "field1")
    languages = next(f for f in read.fields if f.label.startswith("Language Skill"))
    assert languages.kind == "multiselect" and {"label": "English (ENG)", "value": "English (ENG)"} in languages.options
    why = next(f for f in read.fields if f.label == "Why do you want to work at Palantir?")
    assert why.kind == "textarea" and not why.required


def test_lever_eeo_selects_are_demographic_fields():
    page = """<form><input name="name" required><input name="email" required>
      <select name="eeo[gender]"><option value="">Select ...</option><option value="Male">Male</option>
      <option value="Female">Female</option><option value="Decline to self-identify">Decline to self-identify</option></select>
      <select name="eeo[veteran]"><option value="">Select ...</option><option value="I am not a protected veteran">I am not a protected veteran</option></select>
    </form>"""
    read = forms.parse_lever(page, LEVER_URL + "/apply")
    fields = by_key(read)
    assert fields["eeo[gender]"].section == "demographic"
    assert [o["label"] for o in fields["eeo[gender]"].options] == ["Male", "Female", "Decline to self-identify"]
    assert fields["eeo[veteran]"].label == "Veteran status"


def test_lever_page_without_a_form_is_an_error():
    with pytest.raises(forms.FormReadError):
        forms.parse_lever("<html><body>Job closed</body></html>", LEVER_URL)


def test_ashby_form_definition_becomes_fields():
    http = FakeDiscoveryHttp({("POST", forms.ASHBY_GRAPHQL_URL): json_result(fixture_json("ashby_job_posting.json"))})
    read = forms.read_form(http, ASHBY_URL + "/application")
    assert read.ats is WatchAts.ASHBY and read.apply_url == ASHBY_URL + "/application"
    assert http.calls[0].body["variables"] == {"organizationHostedJobsPageName": "ramp", "jobPostingId": ASHBY_ID}
    fields = by_key(read)
    assert fields["_systemfield_name"].label == "Legal Name"
    assert fields["_systemfield_resume"].kind == "file" and fields["_systemfield_resume"].required
    kinds = {f.kind for f in read.fields}
    assert {"text", "file", "boolean", "textarea"} <= kinds


def test_ashby_closed_job_is_an_error():
    http = FakeDiscoveryHttp({("POST", forms.ASHBY_GRAPHQL_URL): json_result({"data": {"jobPosting": None}})})
    with pytest.raises(forms.FormReadError, match="closed"):
        forms.read_form(http, ASHBY_URL)


def test_other_sites_are_unsupported():
    with pytest.raises(forms.UnsupportedBoardError):
        forms.read_form(FakeDiscoveryHttp(), "https://careers.google.com/jobs/123")
    assert forms.job_ref("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Intern_R1") is None


def test_board_404_and_other_failures_are_readable():
    http = FakeDiscoveryHttp({("GET", GH_API): DiscoveryFetchError("boards-api.greenhouse.io: HTTP 404", status=404)})
    with pytest.raises(forms.FormReadError, match="no longer exists"):
        forms.read_form(http, GH_URL)
    http = FakeDiscoveryHttp({("GET", GH_API): DiscoveryFetchError("boards-api.greenhouse.io: timed out")})
    with pytest.raises(forms.FormReadError, match="timed out"):
        forms.read_form(http, GH_URL)


def test_untrusted_text_is_cleaned_and_capped():
    data = {
        "questions": [
            {"label": "<b>Why</b> &amp; " + "x" * 2000, "required": True, "fields": [{"name": "q1", "type": "textarea"}]},
            {"label": "Pick", "fields": [{"name": "q2", "type": "multi_value_single_select",
                                         "values": [{"label": "<i>A</i>", "value": 1}, {"label": "", "value": 2}]}]},
            {"label": "Odd", "fields": [{"name": "q3", "type": "something_new"}]},
            "not a question",
        ]
    }
    fields = by_key(forms.parse_greenhouse(data, GH_URL))
    assert fields["q1"].label.startswith("Why & x") and len(fields["q1"].label) == forms.MAX_LABEL
    assert fields["q2"].options == [{"label": "A", "value": "1"}]
    assert "q3" not in fields


def test_garbage_responses_are_errors():
    with pytest.raises(forms.FormReadError):
        forms.parse_greenhouse(["nope"], GH_URL)
    with pytest.raises(forms.FormReadError):
        forms.parse_ashby("nope", ASHBY_URL)
