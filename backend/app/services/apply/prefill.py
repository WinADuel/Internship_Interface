"""Fill a read form from the apply profile and the saved answers.

Each field gets `{"value": ..., "source": ...}`: the value is text for a text
field, an option label for a select or yes/no field, a list of option labels
for a multi-select, and the resume's file name for the resume upload. The
source says where it came from ("profile", "saved"), so the review page can
show what still needs the owner ("" means nothing matched).

Matching is deliberately conservative: a field is only filled when its key
or label clearly asks for a profile value, and a select only when one of its
options clearly matches. A wrong answer is worse than a blank one, because
the owner reviews blanks but may skim past a confident wrong value."""

import re
from collections.abc import Callable
from typing import Any

from app.services.apply.forms import BOOLEAN, DEMOGRAPHIC, FILE, MULTISELECT, SELECT, TEXTAREA

PROFILE, SAVED = "profile", "saved"

# Values a profile yes/no/decline field may hold.
YES, NO, DECLINE = "yes", "no", "decline"

_DECLINE_WORDS = (
    "decline",
    "don't wish",
    "do not wish",
    "don’t wish",
    "prefer not",
    "not to answer",
    "choose not",
    "not wish to",
    "rather not",
    "not to disclose",
    "not to self-identify",
    "not to identify",
)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9+]+", " ", text.lower()).split())


def _words(text: str) -> set[str]:
    return set(_norm(text).split())


def _full_name(p: dict[str, str]) -> str:
    return " ".join(x for x in (p.get("first_name", ""), p.get("last_name", "")) if x)


def _location(p: dict[str, str]) -> str:
    return ", ".join(x for x in (p.get("city", ""), p.get("state", "")) if x)


def _graduation(p: dict[str, str]) -> str:
    return " ".join(x for x in (p.get("graduation_month", ""), p.get("graduation_year", "")) if x)


def _get(name: str) -> Callable[[dict[str, str]], str]:
    return lambda p: p.get(name, "")


# Keys the boards use for their standard fields, whatever the label says.
_BY_KEY: dict[str, Callable[[dict[str, str]], str]] = {
    # Greenhouse
    "first_name": _get("first_name"),
    "last_name": _get("last_name"),
    "preferred_name": _get("preferred_name"),
    "email": _get("email"),
    "phone": _get("phone"),
    # Lever
    "name": _full_name,
    "location": _location,
    "org": _get("current_company"),
    "urls[LinkedIn]": _get("linkedin_url"),
    "urls[GitHub]": _get("github_url"),
    "urls[Portfolio]": _get("website_url"),
    "pronouns": _get("pronouns"),
    "eeo[gender]": _get("gender"),
    "eeo[race]": _get("race"),
    "eeo[veteran]": _get("veteran"),
    "eeo[disability]": _get("disability"),
    # Ashby
    "_systemfield_name": _full_name,
    "_systemfield_email": _get("email"),
    "_systemfield_phone": _get("phone"),
    "_systemfield_location": _location,
}

# (pattern on the normalized label, value). First match wins, so the more
# specific patterns come first. Demographic rules only apply to fields in
# the demographic section or whose label is unmistakably demographic.
_BY_LABEL: list[tuple[re.Pattern[str], Callable[[dict[str, str]], str]]] = [
    (re.compile(r"\blinkedin\b"), _get("linkedin_url")),
    (re.compile(r"\bgithub\b"), _get("github_url")),
    (re.compile(r"\b(portfolio|personal website|website|personal site)\b"), _get("website_url")),
    (re.compile(r"^(legal )?first name\b"), _get("first_name")),
    (re.compile(r"^(legal )?last name\b|^surname\b|^family name\b"), _get("last_name")),
    (re.compile(r"^preferred (first )?name\b"), lambda p: p.get("preferred_name") or p.get("first_name", "")),
    (re.compile(r"^(full |legal )?name$|^full legal name$|^legal name$"), _full_name),
    (re.compile(r"^(e ?mail|email address)$"), _get("email")),
    (re.compile(r"^(phone|phone number|mobile|mobile phone|cell phone)$"), _get("phone")),
    (re.compile(r"\bpronouns?\b"), _get("pronouns")),
    (re.compile(r"\b(sponsorship|sponsor|visa)\b"), _get("needs_sponsorship")),
    (re.compile(r"\b(legally )?(authorized|authorised|eligible) to work\b|\bwork authori[sz]ation\b"), _get("work_authorized")),
    (re.compile(r"\brelocat"), _get("willing_to_relocate")),
    (re.compile(r"\b(gpa|grade point average)\b"), _get("gpa")),
    (re.compile(r"\b(graduation|graduate|grad) (date|year|month)\b|\bexpected graduation\b|\bwhen do you graduate\b|\bwhen will you graduate\b"), _graduation),
    (re.compile(r"\b(major|discipline|field of study|area of study)\b"), _get("major")),
    (re.compile(r"\bdegree\b"), _get("degree")),
    (re.compile(r"^(school|university|college|school name|university name)$|\b(which|what) (university|school|college)\b|\bcurrently attend"), _get("school")),
    (re.compile(r"\bhow did you (hear|learn|find)\b|\bwhere did you (hear|learn|find)\b|\bsource\b.*\bapplication\b"), _get("how_heard")),
    (re.compile(r"^(current )?(company|employer)$|\bcurrent (company|employer)\b"), _get("current_company")),
    (re.compile(r"^(location|current location|location city|city|where are you located)$"), _location),
]

_DEMOGRAPHIC_BY_LABEL: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(hispanic|latino|latina|latinx|latine)\b.*\?|^are you hispanic"), "hispanic_latino"),
    (re.compile(r"\blgbt"), "lgbtq"),
    (re.compile(r"\bveteran\b"), "veteran"),
    (re.compile(r"\bdisabilit"), "disability"),
    (re.compile(r"\b(race|ethnicity)\b"), "race"),
    (re.compile(r"\bgender\b|^sex$"), "gender"),
]


def _profile_value(field: dict[str, Any], profile: dict[str, str]) -> str:
    key, label = field["key"], _norm(field["label"])
    if key in _BY_KEY:
        return _BY_KEY[key](profile)
    is_demographic = field.get("section") == DEMOGRAPHIC
    for pattern, name in _DEMOGRAPHIC_BY_LABEL:
        if pattern.search(label) and (is_demographic or field["kind"] in (SELECT, MULTISELECT)):
            return profile.get(name, "")
    if is_demographic:
        return ""
    for pattern, getter in _BY_LABEL:
        if pattern.search(label):
            return getter(profile)
    return ""


# --- choosing an option ------------------------------------------------------------


def _is_decline(label: str) -> bool:
    low = label.lower()
    return any(w in low for w in _DECLINE_WORDS)


def _pick(options: list[dict[str, str]], value: str) -> str | None:
    """The option label that `value` clearly means, else None."""
    labels = [o["label"] for o in options]
    if not labels or not value:
        return None
    want = _norm(value)
    if value.lower() == DECLINE:
        return next((label for label in labels if _is_decline(label)), None)
    exact = [label for label in labels if _norm(label) == want]
    if exact:
        return exact[0]
    if want in (YES, NO):
        starts = [label for label in labels if _norm(label).split()[:1] == [want] and not _is_decline(label)]
        if len(starts) == 1:
            return starts[0]
        # Veteran questions: "I am not a protected veteran" / "I identify as ... a protected veteran".
        negative = [label for label in labels if re.search(r"\b(not|no)\b", _norm(label)) and not _is_decline(label)]
        positive = [label for label in labels if label not in negative and not _is_decline(label)]
        pool = negative if want == NO else positive
        return pool[0] if len(pool) == 1 else None
    # A whole-word match, unambiguous: "Asian" in "Asian (Not Hispanic or Latino)",
    # but never "Male" for "Female".
    pattern = re.compile(rf"(^|\s){re.escape(want)}(\s|$)")
    contains = [label for label in labels if pattern.search(_norm(label)) and not _is_decline(label)]
    if len(contains) == 1:
        return contains[0]
    starts = [label for label in labels if _norm(label).startswith(want)]
    return starts[0] if len(starts) == 1 else None


def _boolean(value: str) -> str | None:
    v = _norm(value)
    if v in ("yes", "true"):
        return "Yes"
    if v in ("no", "false"):
        return "No"
    return None


# --- saved answers -----------------------------------------------------------------


def saved_answer(label: str, saved: list[dict[str, str]]) -> str | None:
    """A saved answer whose question is the same as `label`: equal once
    normalized, or nearly the same words (at least 4 words, 85% overlap)."""
    want = _norm(label)
    if not want:
        return None
    for item in saved:
        if _norm(item.get("question", "")) == want:
            return item.get("answer", "")
    words = _words(label)
    if len(words) < 4:
        return None
    best, best_score = None, 0.0
    for item in saved:
        other = _words(item.get("question", ""))
        if len(other) < 4:
            continue
        score = len(words & other) / len(words | other)
        if score > best_score:
            best, best_score = item.get("answer", ""), score
    return best if best_score >= 0.85 else None


def _shaped(field: dict[str, Any], value: str) -> str | list[str] | None:
    """`value` in the field's shape, or None if it doesn't fit."""
    kind = field["kind"]
    if not value:
        return None
    if kind == BOOLEAN:
        return _boolean(value)
    if kind == SELECT:
        return _pick(field.get("options") or [], value)
    if kind == MULTISELECT:
        parts = [p.strip() for p in re.split(r"[;,\n]", value) if p.strip()]
        picked = [p for p in (_pick(field.get("options") or [], part) for part in parts) if p]
        return list(dict.fromkeys(picked)) or None
    return value


def prefill(
    form: list[dict[str, Any]],
    profile: dict[str, str],
    saved: list[dict[str, str]],
    resume_filename: str | None,
) -> dict[str, dict[str, Any]]:
    answers: dict[str, dict[str, Any]] = {}
    for field in form:
        key, kind = field["key"], field["kind"]
        if kind == FILE:
            if resume_filename and re.search(r"resume|\bcv\b", field["label"].lower() + " " + key.lower()):
                answers[key] = {"value": resume_filename, "source": PROFILE}
            continue
        value = _shaped(field, _profile_value(field, profile))
        source = PROFILE
        if value is None and field.get("section") != DEMOGRAPHIC:
            value, source = _shaped(field, saved_answer(field["label"], saved) or ""), SAVED
        if value is not None:
            answers[key] = {"value": value, "source": source}
    return answers


def empty_value(field: dict[str, Any]) -> str | list[str]:
    return [] if field["kind"] == MULTISELECT else ""


def is_open_question(field: dict[str, Any]) -> bool:
    """A question the local AI may draft: free text, outside the demographic section."""
    return field["kind"] in (TEXTAREA,) and field.get("section") != DEMOGRAPHIC
