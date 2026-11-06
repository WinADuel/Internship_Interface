"""Read a job's application form from Greenhouse, Lever or Ashby and turn it
into one plain list of fields.

Each board publishes its form in its own shape:

- Greenhouse: the public Job Board API, `?questions=true`, lists every
  question with its field names (the same names are the input ids on the
  hosted form) plus the voluntary demographic questions.
- Lever: there is no public form API, so the hosted apply page is read. Its
  standard fields have fixed names, and each custom question card carries
  its full definition as JSON in a hidden `baseTemplate` input.
- Ashby: the hosted job page's own GraphQL endpoint returns the form
  definition (field paths, types and choices).

Every request goes through `DiscoveryHttp`, so the SSRF guard applies and
tests never touch the network. Everything read is untrusted: labels and
options are capped and stripped of markup here."""

import html
import json
import re
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any

from app.models.watch_company import WatchAts
from app.services.discovery.http import DiscoveryFetchError, DiscoveryHttp
from app.services.discovery.urls import JobRef, parse_job_url

FORM_MAX_BYTES = 5 * 1024 * 1024
FORM_TIMEOUT = 20.0
MAX_FIELDS = 150
MAX_OPTIONS = 2000
MAX_LABEL = 500
MAX_KEY = 200
MAX_DESCRIPTION = 1000

# Field kinds the review page and the extension understand.
TEXT, TEXTAREA, SELECT, MULTISELECT, BOOLEAN, FILE = (
    "text",
    "textarea",
    "select",
    "multiselect",
    "boolean",
    "file",
)
APPLICATION, DEMOGRAPHIC = "application", "demographic"


class FormReadError(Exception):
    """One-line, user-safe reason the form couldn't be read."""


class UnsupportedBoardError(FormReadError):
    pass


@dataclass
class FormField:
    key: str
    label: str
    kind: str
    required: bool = False
    options: list[dict[str, str]] = field(default_factory=list)  # [{"label", "value"}]
    section: str = APPLICATION
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReadForm:
    ats: WatchAts
    apply_url: str
    fields: list[FormField]


# --- text clean-up -----------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def _plain(value: object, limit: int) -> str:
    """Markup removed, entities decoded, whitespace collapsed, capped."""
    if value is None:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", str(value)))
    text = "".join(" " if ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F else c for c in text)
    return " ".join(text.split())[:limit]


def _option(label: object, value: object = None) -> dict[str, str] | None:
    text = _plain(label, MAX_LABEL)
    if not text:
        return None
    return {"label": text, "value": _plain(value if value is not None else label, MAX_LABEL)}


def _options(items: list[tuple[object, object]]) -> list[dict[str, str]]:
    out = [o for o in (_option(label, value) for label, value in items) if o is not None]
    return out[:MAX_OPTIONS]


def _add(fields: list[FormField], f: FormField) -> None:
    if f.key and f.label and len(fields) < MAX_FIELDS and all(x.key != f.key for x in fields):
        f.key = f.key[:MAX_KEY]
        fields.append(f)


# --- Greenhouse ----------------------------------------------------------------

_GREENHOUSE_KINDS = {
    "input_text": TEXT,
    "textarea": TEXTAREA,
    "input_file": FILE,
    "multi_value_single_select": SELECT,
    "multi_value_multi_select": MULTISELECT,
}


def greenhouse_api_url(ref: JobRef) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{ref.token}/jobs/{ref.job_id}?questions=true"


def greenhouse_apply_url(ref: JobRef) -> str:
    return f"https://job-boards.greenhouse.io/{ref.token}/jobs/{ref.job_id}"


def parse_greenhouse(data: Any, apply_url: str) -> ReadForm:
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise FormReadError("Greenhouse didn't return an application form for this job")
    fields: list[FormField] = []
    for q in data["questions"]:
        if not isinstance(q, dict) or not isinstance(q.get("fields"), list):
            continue
        label = _plain(q.get("label"), MAX_LABEL)
        names = {f.get("name") for f in q["fields"] if isinstance(f, dict)}
        for f in q["fields"]:
            if not isinstance(f, dict):
                continue
            name, kind = str(f.get("name") or ""), _GREENHOUSE_KINDS.get(str(f.get("type")))
            if kind is None:  # input_hidden and anything new
                continue
            # "Resume/CV" is a file input plus an "Enter manually" text box: keep the file.
            if kind == TEXTAREA and name.endswith("_text") and name[: -len("_text")] in names:
                continue
            values = f.get("values") if isinstance(f.get("values"), list) else []
            _add(
                fields,
                FormField(
                    key=name,
                    label=label,
                    kind=kind,
                    required=bool(q.get("required")),
                    options=_options([(v.get("label"), v.get("value")) for v in values if isinstance(v, dict)]),
                    description=_plain(q.get("description"), MAX_DESCRIPTION),
                ),
            )
    for q in data.get("location_questions") or []:
        if isinstance(q, dict):
            for f in q.get("fields") or []:
                if isinstance(f, dict) and f.get("type") == "input_text":
                    _add(fields, FormField(key=str(f.get("name") or ""), label=_plain(q.get("label"), MAX_LABEL),
                                           kind=TEXT, required=bool(q.get("required"))))
    demographic = data.get("demographic_questions")
    if isinstance(demographic, dict):
        for q in demographic.get("questions") or []:
            if not isinstance(q, dict):
                continue
            answers = q.get("answer_options") if isinstance(q.get("answer_options"), list) else []
            _add(
                fields,
                FormField(
                    # The hosted form's input id for a demographic question is its id.
                    key=str(q.get("id") or ""),
                    label=_plain(q.get("label"), MAX_LABEL),
                    kind=MULTISELECT if q.get("type") == "multi_value_multi_select" else SELECT,
                    required=bool(q.get("required")),
                    options=_options([(a.get("label"), a.get("id")) for a in answers if isinstance(a, dict)]),
                    section=DEMOGRAPHIC,
                ),
            )
    # Older boards put the EEOC questions under "compliance".
    for block in data.get("compliance") or []:
        if not isinstance(block, dict):
            continue
        for q in block.get("questions") or []:
            if not isinstance(q, dict):
                continue
            for f in q.get("fields") or []:
                if isinstance(f, dict) and f.get("type") == "multi_value_single_select":
                    values = f.get("values") if isinstance(f.get("values"), list) else []
                    _add(
                        fields,
                        FormField(
                            key=str(f.get("name") or ""),
                            label=_plain(q.get("label"), MAX_LABEL),
                            kind=SELECT,
                            required=bool(q.get("required")),
                            options=_options([(v.get("label"), v.get("value")) for v in values if isinstance(v, dict)]),
                            section=DEMOGRAPHIC,
                        ),
                    )
    return ReadForm(WatchAts.GREENHOUSE, apply_url, fields)


# --- Lever -------------------------------------------------------------------

LEVER_STANDARD: list[tuple[str, str, str]] = [
    ("resume", "Resume/CV", FILE),
    ("name", "Full name", TEXT),
    ("email", "Email", TEXT),
    ("phone", "Phone", TEXT),
    ("location", "Current location", TEXT),
    ("org", "Current company", TEXT),
    ("urls[LinkedIn]", "LinkedIn URL", TEXT),
    ("urls[GitHub]", "GitHub URL", TEXT),
    ("urls[Twitter]", "Twitter URL", TEXT),
    ("urls[Portfolio]", "Portfolio URL", TEXT),
    ("urls[Other]", "Other website", TEXT),
    ("pronouns", "Pronouns", TEXT),
    ("comments", "Additional information", TEXTAREA),
]
_LEVER_EEO_LABELS = {
    "gender": "Gender",
    "race": "Race",
    "veteran": "Veteran status",
    "disability": "Disability status",
}
_LEVER_CARD_KINDS = {
    "text": TEXT,
    "textarea": TEXTAREA,
    "multiple-choice": SELECT,
    "dropdown": SELECT,
    "multiple-select": MULTISELECT,
    "yes-no": BOOLEAN,
}


class _LeverPage(HTMLParser):
    """Collects the names of the form's inputs, which inputs are required,
    each select's options and each card's hidden baseTemplate JSON."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.names: set[str] = set()
        self.required: set[str] = set()
        self.templates: list[tuple[str, str]] = []  # (card id, JSON)
        self.selects: dict[str, list[tuple[str, str]]] = {}
        self._select: str | None = None
        self._option_value: str | None = None
        self._option_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        name = a.get("name", "")
        if tag in ("input", "textarea", "select") and name:
            m = re.fullmatch(r"cards\[([0-9a-fA-F-]{1,64})\]\[baseTemplate\]", name)
            if m and tag == "input":
                self.templates.append((m.group(1), a.get("value", "")))
                return
            self.names.add(name)
            if "required" in a:
                self.required.add(name)
            if tag == "select":
                self._select = name
                self.selects.setdefault(name, [])
        elif tag == "option" and self._select is not None:
            self._option_value = a.get("value", "")
            self._option_text = []

    def handle_data(self, data: str) -> None:
        if self._option_value is not None:
            self._option_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._select is not None and self._option_value is not None:
            text = "".join(self._option_text).strip()
            if self._option_value:  # the placeholder "Select ..." has no value
                self.selects[self._select].append((text, self._option_value))
            self._option_value = None
        elif tag == "select":
            self._select = None


def lever_apply_url(ref: JobRef) -> str:
    return f"https://jobs.lever.co/{ref.token}/{ref.job_id}/apply"


def parse_lever(page: str, apply_url: str) -> ReadForm:
    parser = _LeverPage()
    parser.feed(page)
    parser.close()
    if "name" not in parser.names and "email" not in parser.names:
        raise FormReadError("Lever's page for this job has no application form")
    fields: list[FormField] = []
    for key, label, kind in LEVER_STANDARD:
        if key in parser.names:
            _add(fields, FormField(key=key, label=label, kind=kind, required=key in parser.required))
    for card_id, raw in parser.templates:
        try:
            card = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(card, dict) or not isinstance(card.get("fields"), list):
            continue
        for i, f in enumerate(card["fields"]):
            if not isinstance(f, dict):
                continue
            kind = _LEVER_CARD_KINDS.get(str(f.get("type")))
            if kind is None:
                continue
            options = f.get("options") if isinstance(f.get("options"), list) else []
            _add(
                fields,
                FormField(
                    key=f"cards[{card_id}][field{i}]",
                    label=_plain(f.get("text"), MAX_LABEL),
                    kind=kind,
                    required=bool(f.get("required")),
                    options=_options([(o.get("text"), o.get("text")) for o in options if isinstance(o, dict)]),
                    description=_plain(f.get("description"), MAX_DESCRIPTION),
                ),
            )
    for name, options in parser.selects.items():
        m = re.fullmatch(r"eeo\[([a-z]+)\]", name)
        if m:
            _add(
                fields,
                FormField(
                    key=name,
                    label=_LEVER_EEO_LABELS.get(m.group(1), m.group(1).capitalize()),
                    kind=SELECT,
                    options=_options(options),
                    section=DEMOGRAPHIC,
                ),
            )
    return ReadForm(WatchAts.LEVER, apply_url, fields)


# --- Ashby ---------------------------------------------------------------------

ASHBY_GRAPHQL_URL = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting"
_ASHBY_QUERY = (
    "query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {"
    " jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {"
    " id title"
    " applicationForm { sections { title fieldEntries { ... on FormFieldEntry { id field isRequired descriptionHtml } } } }"
    " surveyForms { sections { title fieldEntries { ... on FormFieldEntry { id field isRequired descriptionHtml } } } }"
    " } }"
)
_ASHBY_KINDS = {
    "String": TEXT,
    "Email": TEXT,
    "Phone": TEXT,
    "Location": TEXT,
    "SocialLink": TEXT,
    "Number": TEXT,
    "Date": TEXT,
    "LongText": TEXTAREA,
    "File": FILE,
    "Boolean": BOOLEAN,
    "ValueSelect": SELECT,
    "MultiValueSelect": MULTISELECT,
}


def ashby_body(ref: JobRef) -> dict:
    return {
        "operationName": "ApiJobPosting",
        "variables": {"organizationHostedJobsPageName": ref.token, "jobPostingId": ref.job_id},
        "query": _ASHBY_QUERY,
    }


def ashby_apply_url(ref: JobRef) -> str:
    return f"https://jobs.ashbyhq.com/{ref.token}/{ref.job_id}/application"


def _ashby_sections(form: Any, section: str, fields: list[FormField]) -> None:
    if not isinstance(form, dict):
        return
    for s in form.get("sections") or []:
        if not isinstance(s, dict):
            continue
        for entry in s.get("fieldEntries") or []:
            if not isinstance(entry, dict) or not isinstance(entry.get("field"), dict):
                continue
            f = entry["field"]
            kind = _ASHBY_KINDS.get(str(f.get("type")))
            if kind is None:
                continue
            values = f.get("selectableValues") if isinstance(f.get("selectableValues"), list) else []
            _add(
                fields,
                FormField(
                    key=str(f.get("path") or ""),
                    label=_plain(f.get("title"), MAX_LABEL),
                    kind=kind,
                    required=bool(entry.get("isRequired")),
                    options=_options([(v.get("label"), v.get("value")) for v in values if isinstance(v, dict)]),
                    section=section,
                    description=_plain(entry.get("descriptionHtml"), MAX_DESCRIPTION),
                ),
            )


def parse_ashby(data: Any, apply_url: str) -> ReadForm:
    posting = data.get("data", {}).get("jobPosting") if isinstance(data, dict) else None
    if not isinstance(posting, dict):
        raise FormReadError("Ashby didn't return this job (it may have closed)")
    fields: list[FormField] = []
    _ashby_sections(posting.get("applicationForm"), APPLICATION, fields)
    for survey in posting.get("surveyForms") or []:
        _ashby_sections(survey, DEMOGRAPHIC, fields)
    return ReadForm(WatchAts.ASHBY, apply_url, fields)


# --- entry point -------------------------------------------------------------

SUPPORTED_ATS = (WatchAts.GREENHOUSE, WatchAts.LEVER, WatchAts.ASHBY)


def job_ref(url: str) -> JobRef | None:
    """The Greenhouse, Lever or Ashby job a posting URL points at, else None."""
    ref = parse_job_url(url)
    return ref if ref is not None and ref.ats in SUPPORTED_ATS else None


def read_form(http: DiscoveryHttp, url: str) -> ReadForm:
    ref = job_ref(url)
    if ref is None:
        raise UnsupportedBoardError(
            "Auto-apply reads Greenhouse, Lever and Ashby forms; this posting's link is on another site"
        )
    try:
        if ref.ats is WatchAts.GREENHOUSE:
            result = http.get_json(greenhouse_api_url(ref), max_bytes=FORM_MAX_BYTES, timeout=FORM_TIMEOUT)
            # Always the hosted form: a company's own careers page that embeds
            # it is a site the extension doesn't run on.
            return parse_greenhouse(result.data, greenhouse_apply_url(ref))
        if ref.ats is WatchAts.LEVER:
            apply_url = lever_apply_url(ref)
            result = http.get_page(apply_url, max_bytes=FORM_MAX_BYTES, timeout=FORM_TIMEOUT)
            return parse_lever(result.text or "", apply_url)
        result = http.post_json(ASHBY_GRAPHQL_URL, ashby_body(ref), max_bytes=FORM_MAX_BYTES, timeout=FORM_TIMEOUT)
        return parse_ashby(result.data, ashby_apply_url(ref))
    except DiscoveryFetchError as exc:
        if exc.status == 404:
            raise FormReadError("The job board says this job no longer exists") from None
        raise FormReadError(f"Couldn't read the application form: {exc}") from None
