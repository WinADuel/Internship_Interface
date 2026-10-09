"""Email matching (Phase 6 spec §4): pure functions that turn one message's
parsed headers plus a snapshot of applications and contacts into at most one
suggestion. Nothing here reads the database or the network.

Order: a tracked contact (§4.1) first; then, for inbound mail only, an
application at the sender's company (§4.2) with the classifier's kind (§4.3);
then a new-application suggestion for applicant-tracking-system mail from a
company that isn't tracked yet (§4.4)."""

import enum
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.models.contact import ContactStatus
from app.services.gmail.classify import SuggestionKind, classify, normalize_text


class Direction(str, enum.Enum):
    INBOUND = "inbound"
    SENT = "sent"


@dataclass(frozen=True)
class EmailHeaders:
    """What the sync keeps of a message: parsed headers and Gmail's snippet.
    Addresses are bare (no display names); case does not matter."""

    direction: Direction
    from_name: str
    from_email: str
    subject: str
    snippet: str
    received_at: datetime
    to_emails: tuple[str, ...] = ()
    cc_emails: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApplicationRef:
    id: int
    company: str
    role_title: str
    status: str
    archived: bool
    updated_at: datetime


@dataclass(frozen=True)
class ContactRef:
    id: int
    email: str | None
    status: str
    application_id: int | None


@dataclass(frozen=True)
class Snapshot:
    applications: Sequence[ApplicationRef] = ()
    contacts: Sequence[ContactRef] = ()


@dataclass(frozen=True)
class Proposal:
    kind: SuggestionKind
    application_id: int | None = None
    contact_id: int | None = None
    proposed_company: str | None = None
    proposed_role: str | None = None


# Applicant-tracking systems (spec §4.2). A host matches when it equals an
# entry or ends with "." + entry.
ATS_DOMAINS = (
    "greenhouse.io",
    "greenhouse-mail.io",
    "lever.co",
    "hire.lever.co",
    "ashbyhq.com",
    "myworkday.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "icims.com",
    "jobvite.com",
    "successfactors.com",
    "taleo.net",
    "eightfold.ai",
    "gem.com",
    "rippling.com",
    "workablemail.com",
)
# Display names these systems use for themselves; never a company to add.
_ATS_BRANDS = frozenset(
    {
        "greenhouse",
        "lever",
        "workday",
        "ashby",
        "smartrecruiters",
        "icims",
        "jobvite",
        "taleo",
        "successfactors",
        "sapsuccessfactors",
        "eightfold",
        "gem",
        "rippling",
        "workable",
        "noreply",
        "donotreply",
        "notifications",
        "notification",
        "mailer",
    }
)
# Job boards and mailing platforms send digests naming many companies; their
# display names ("Stripe via LinkedIn", "The Square Deal") never identify the
# employer. Their own domain can still match an application at that company.
_BULK_SENDER_DOMAINS = (
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "joinhandshake.com",
    "handshake.com",
    "ziprecruiter.com",
    "wellfound.com",
    "angel.co",
    "simplify.jobs",
    "builtin.com",
    "ripplematch.com",
    "levels.fyi",
    "substack.com",
    "beehiiv.com",
    "medium.com",
    "mailchimpapp.com",
    "mcsv.net",
)
_DIGEST_SUBJECT = re.compile(
    r"(?<![a-z0-9])(?:job alerts?|jobs? (?:you may|for you|picked for you|recommended)|"
    r"recommended jobs|new jobs|(?:is|are) hiring|newsletter|digest|webinar)(?![a-z0-9])"
)
# Bulk-mail sender addresses (jobalerts-noreply@, newsletter@, marketing@).
_DIGEST_LOCAL = re.compile(r"alert|digest|newsletter|marketing|promo")
# Direct mail from a company (not an ATS) must look job-related, so Apple's
# "Unfortunately, your order is delayed" or Box's "pleased to offer you a free
# trial" don't become rejections and offers.
_JOB_CONTEXT = re.compile(
    r"(?<![a-z0-9])(?:applica\w*|apply\w*|applied|candida\w*|positions?|roles?|interns?|"
    r"internships?|co-?op|recruit\w*|interview\w*|hiring|talent|careers?|jobs?|"
    r"offer letter|offer of employment|hackerrank|codesignal|codility|assessments?|"
    r"university|campus)(?![a-z0-9])"
)
_COMPANY_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "company",
        "gmbh",
        "plc",
        "technologies",
        "technology",
        "holdings",
        "group",
        "the",
    }
)
# Trailing/leading words on an ATS display name that aren't the company
# ("Rivian Recruiting", "Hiring Team at Rivian", "Rivian via Greenhouse").
_NAME_TAIL = re.compile(
    r"(?:\s*(?:[-|,@:–—]|\bvia\b|\bat\b|\bfrom\b)?\s*"
    r"(?:via\s+\w+|university\s+recruiting|campus\s+recruiting|recruiting(?:\s+team)?|"
    r"recruitment|recruiters?|hiring\s+team|hiring|talent\s+acquisition(?:\s+team)?|"
    r"talent(?:\s+team)?|careers?|jobs|people\s+team|hr|team))+\s*$",
    re.IGNORECASE,
)
_NAME_HEAD = re.compile(
    r"^\s*(?:the\s+)?(?:university\s+recruiting|recruiting|hiring|talent\s+acquisition|careers?|jobs)"
    r"(?:\s+team)?\s+(?:at|@|for)\s+",
    re.IGNORECASE,
)
_ROLE_PATTERNS = (
    re.compile(
        r"\b(?:applying|applied|application)\s+(?:to|for)\s+(?:the\s+)?"
        r"(?P<role>[^.,;!?\n]{3,100}?)\s+(?:position|role|opening)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:applying|applied|application)\s+(?:to|for)\s+(?:the\s+)?"
        r"(?P<role>[^.,;!?\n]{3,100}?)\s+(?:at|with)\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfor\s+(?:the|our)\s+(?P<role>[^.,;!?\n]{3,100}?)\s+(?:position|role)\b",
        re.IGNORECASE,
    ),
)
_MAX_PROPOSED = 200


def _tokens(text: str | None) -> tuple[str, ...]:
    """Lower-case alphanumeric words, accents stripped ("Macy's" -> macy, s)."""
    if not text:
        return ()
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return tuple(re.findall(r"[a-z0-9]+", folded.replace("&", " ")))


def company_tokens(name: str | None) -> tuple[str, ...]:
    """A company name's words without punctuation and suffixes like "Inc",
    "LLC" or "Technologies" ("Palantir Technologies Inc." -> palantir)."""
    words = _tokens(name)
    kept = tuple(w for w in words if w not in _COMPANY_SUFFIXES)
    return kept or words


def company_key(name: str | None) -> str:
    """The joined company tokens ("Jane Street" -> janestreet), the form a
    company takes in its email domain. Empty when it has under 3 letters, so
    names like "X" or "HP" never match on their own."""
    key = "".join(company_tokens(name))
    return key if sum(c.isalpha() for c in key) >= 3 else ""


def _split_email(address: str | None) -> tuple[str, str]:
    address = (address or "").strip().casefold()
    local, _, domain = address.rpartition("@")
    return local, domain.rstrip(".")


def _host_in(domain: str, suffixes: Iterable[str]) -> bool:
    return any(domain == s or domain.endswith("." + s) for s in suffixes)


def is_ats_sender(email: str | None) -> bool:
    return _host_in(_split_email(email)[1], ATS_DOMAINS)


def _contains_run(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def _names_company(text_tokens: tuple[str, ...], company: str) -> bool:
    """Whether a text names the company as whole words: its tokens in a row,
    or one word equal to the joined key ("JaneStreet")."""
    key = company_key(company)
    if not key:
        return False
    return _contains_run(text_tokens, company_tokens(company)) or key in text_tokens


def _domain_names_company(domain: str, company: str) -> bool:
    key = company_key(company)
    labels = domain.split(".")[:-1]  # drop the top-level domain
    return bool(key) and key in labels


def _pick(candidates: list[ApplicationRef], text_tokens: tuple[str, ...]) -> ApplicationRef | None:
    """Among matching applications: the most specific company name, then the
    role title named in the subject/snippet (longest wins), then the most
    recently updated."""
    if not candidates:
        return None

    def rank(app: ApplicationRef) -> tuple[int, int, datetime]:
        role = _tokens(app.role_title)
        role_hit = len(role) if _contains_run(text_tokens, role) else 0
        return (len(company_tokens(app.company)), role_hit, app.updated_at)

    return max(candidates, key=rank)


def _display_company(from_name: str | None) -> str:
    """The company an ATS display name stands for, or "" when the name is the
    ATS itself, a no-reply label, or only recruiting words."""
    name = (from_name or "").strip().strip("\"'").strip()
    previous = None
    while previous != name:
        previous = name
        name = _NAME_HEAD.sub("", name)
        name = _NAME_TAIL.sub("", name).strip(" -|,@:–—")
    key = company_key(name)
    if not key or key in _ATS_BRANDS:
        return ""
    return name[:_MAX_PROPOSED]


def extract_role(subject: str, snippet: str) -> str | None:
    """A best-effort role title from the subject, then the snippet
    ("applying to the Software Engineering Intern position at ...")."""
    for text in (subject, snippet):
        for pattern in _ROLE_PATTERNS:
            match = pattern.search(text or "")
            if match:
                role = match.group("role").strip()
                if company_key(role):
                    return role[:_MAX_PROPOSED]
    return None


def match_contact(headers: EmailHeaders, contacts: Sequence[ContactRef]) -> Proposal | None:
    """§4.1: inbound mail from a contact you emailed (`sent`/`followed_up`)
    proposes contact_reply; sent mail to a `to_contact` contact (To, then Cc)
    proposes contact_sent. Among duplicates the lowest id wins."""
    by_email: dict[str, list[ContactRef]] = {}
    for contact in sorted(contacts, key=lambda c: c.id):
        email = (contact.email or "").strip().casefold()
        if email:
            by_email.setdefault(email, []).append(contact)

    if headers.direction == Direction.INBOUND:
        addresses = [headers.from_email]
        # Tuples, not sets: membership by ==, so plain strings and enum
        # members both work.
        eligible: tuple[ContactStatus, ...] = (ContactStatus.SENT, ContactStatus.FOLLOWED_UP)
        kind = SuggestionKind.CONTACT_REPLY
    else:
        addresses = [*headers.to_emails, *headers.cc_emails]
        eligible = (ContactStatus.TO_CONTACT,)
        kind = SuggestionKind.CONTACT_SENT
    for address in addresses:
        for contact in by_email.get((address or "").strip().casefold(), []):
            if contact.status in eligible:
                return Proposal(kind, application_id=contact.application_id, contact_id=contact.id)
    return None


def match_application(
    headers: EmailHeaders, applications: Sequence[ApplicationRef]
) -> ApplicationRef | None:
    """§4.2: the non-archived application an inbound email is about, or None.
    Does not classify; `propose` decides whether the mail matters."""
    if headers.direction != Direction.INBOUND:
        return None
    active = [a for a in applications if not a.archived and company_key(a.company)]
    local, domain = _split_email(headers.from_email)
    name_tokens = _tokens(headers.from_name)
    text_tokens = _tokens(f"{headers.subject} {headers.snippet}")

    if _host_in(domain, ATS_DOMAINS):
        # The display name (or a Workday-style tenant address such as
        # nvidia@myworkday.com) names the employer. Only when it doesn't name
        # any company is the subject/snippet searched, so "check the box below"
        # in Rivian's mail can't match an application at Box.
        sender_tokens = name_tokens + _tokens(local)
        by_sender = [a for a in active if _names_company(sender_tokens, a.company)]
        if by_sender or _display_company(headers.from_name):
            return _pick(by_sender, text_tokens)
        return _pick([a for a in active if _names_company(text_tokens, a.company)], text_tokens)

    by_domain = [a for a in active if _domain_names_company(domain, a.company)]
    if by_domain:
        return _pick(by_domain, text_tokens)
    if _host_in(domain, _BULK_SENDER_DOMAINS):
        return None
    return _pick([a for a in active if _names_company(name_tokens, a.company)], text_tokens)


def propose(headers: EmailHeaders, snapshot: Snapshot) -> Proposal | None:
    """The one suggestion an email produces, or None to drop it untraced."""
    contact = match_contact(headers, snapshot.contacts)
    if contact is not None:
        return contact
    if headers.direction != Direction.INBOUND:
        return None
    if _DIGEST_SUBJECT.search(normalize_text(headers.subject)):
        return None
    if _DIGEST_LOCAL.search(_split_email(headers.from_email)[0]):
        return None
    kind = classify(headers.subject, headers.snippet)
    if kind is None:
        return None

    ats = is_ats_sender(headers.from_email)
    application = match_application(headers, snapshot.applications)
    if application is not None:
        if not ats and not _has_job_context(headers):
            return None
        return Proposal(kind, application_id=application.id)

    if not ats or kind == SuggestionKind.REJECTION:
        return None
    company = _display_company(headers.from_name)
    if not company:
        return None
    key = company_key(company)
    if any(not a.archived and company_key(a.company) == key for a in snapshot.applications):
        return None
    return Proposal(
        SuggestionKind.NEW_APPLICATION,
        proposed_company=company,
        proposed_role=extract_role(headers.subject, headers.snippet),
    )


def _has_job_context(headers: EmailHeaders) -> bool:
    local, _ = _split_email(headers.from_email)
    text = normalize_text(headers.subject, headers.snippet, headers.from_name, local.replace(".", " "))
    return bool(_JOB_CONTEXT.search(text))
