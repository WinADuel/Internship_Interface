"""Email classification (Phase 6 spec §4.3): a pure function of a message's
subject and Gmail snippet. Phrases match whole words, case-insensitively, and
the first kind that matches wins, in the order offer, rejection, interview,
assessment, confirmation. A refused offer ("we are unable to offer you a
position") is a rejection, and rejection wording beats the confirmation
phrase that usually opens it ("Thank you for your interest ... not to move
forward"). Nothing here reads the database or the network."""

import re
import unicodedata

from app.models.email_suggestion import SuggestionKind
from app.models.interview import InterviewKind


def _phrases(*phrases: str) -> re.Pattern[str]:
    """Whole-phrase pattern over normalised text; words may be separated by
    any run of spaces or hyphens ("take home" matches "take-home")."""
    alternatives = "|".join(
        r"[\s\-]+".join(re.escape(word) for word in phrase.split()) for phrase in phrases
    )
    return re.compile(rf"(?<![a-z0-9])(?:{alternatives})(?![a-z0-9])")


_OFFER = _phrases(
    "offer letter",
    "pleased to offer",
    "extend an offer",
    "extend you an offer",
    "offer of employment",
)
_REJECTION = _phrases(
    "not moving forward",
    "move forward with other",
    "moving forward with other",
    "decided not to proceed",
    "no longer under consideration",
    "will not be moving",
    "won't be moving",
    "pursue other candidates",
    "pursue other applicants",
    "pursuing other candidates",
    "pursuing other applicants",
    "not to move forward",
    "not move forward",
    "unable to move forward",
    "not able to move forward",
    "move forward with another",
    "moving forward with another",
    "not be proceeding",
    "not proceed with your",
    "not to proceed",
    "not be progressing",
    "not to progress",
    "not been selected",
    "were not selected",
    "was not selected",
    "not been successful",
    "were unsuccessful",
    "was unsuccessful",
    "been unsuccessful",
    "position has been filled",
    "role has been filled",
    "filled the position",
    "filled the role",
    "no longer considering",
    "decided to go with another",
    "decided to go in a different direction",
)
# "Candidates whose ..." is a rejection only after a decision: "we will only
# contact candidates whose experience matches" is a common confirmation.
_DECIDED_ON_OTHERS = re.compile(
    r"(?<![a-z0-9])(?:decided|chosen|chose|elected|opted)\s+to\s+(?:move|proceed|continue|go)\s+"
    r"(?:forward\s+)?with\s+(?:other\s+|another\s+|a\s+different\s+)?(?:candidates?|applicants?)(?![a-z0-9])"
)
# An offer phrase under a refusal ("unable to offer you a position", "not in
# a position to extend an offer") is a rejection, checked before offers.
_REFUSED_OFFER = re.compile(
    r"(?<![a-z0-9])(?:unable|not\s+able|cannot|can\s?not|can't|won't\s+be\s+able|will\s+not\s+be\s+able"
    r"|not\s+in\s+a\s+position)\s+to\s+(?:offer|extend)\s+(?:you\s+)?(?:a|an|the)\s+"
    r"(?:offer|position|role|job|internship|interview|place|spot|opportunity)(?![a-z0-9])"
)
# "Unfortunately" and "regret to inform" alone are a rejection unless the mail
# is about moving a time ("Unfortunately, we need to reschedule your interview").
_UNFORTUNATELY = _phrases("unfortunately", "regret to inform", "we regret")
_RESCHEDULE = re.compile(r"(?<![a-z0-9])reschedul")
_INTERVIEW_STRONG = _phrases(
    "your availability",
    "schedule a call",
    "schedule an interview",
    "schedule your interview",
    "invite you to interview",
    "invitation to interview",
    "interview invitation",
    "interview request",
    "scheduling page",
    "scheduling link",
)
_SCHEDULING_LINK = re.compile(r"(?<![a-z0-9])(?:calendly\.com|goodtime\.io)(?![a-z0-9])")
# The only interview cues a confirmation can carry and still be an interview:
# confirmations promise interviews in general ("selected candidates will be
# contacted for an interview", "we will reach out to schedule interviews").
_INTERVIEW_WITH_CONFIRMATION = _phrases(
    "your availability",
    "schedule a time with",
    "schedule a call with",
    "schedule time with",
    "invite you to interview",
    "invite you for an interview",
    "like to invite you",
    "like to interview you",
    "like to schedule",
    "love to schedule",
    "invitation to interview",
    "interview invitation",
    "scheduling page",
    "scheduling link",
)
# Weak cues: "interview" and "next steps" also appear in confirmations ("we'll
# reach out if you're selected for an interview") and assessment invitations
# ("the next step in our interview process"), so they need more care.
_INTERVIEW_WORD = _phrases("interview", "interviews")
_NEXT_STEPS = _phrases("next steps")
_INTERVIEW_PROCESS = _phrases("interview process", "interviewing process")
# A conditional clause runs from its opening word to the end of the sentence.
_CONDITIONAL = re.compile(r"(?<![a-z0-9])(?:if|should|once|in case|in the event)(?![a-z0-9])[^.!?;]*")
# Rejection wording uses "should" as advice ("we feel we should not move
# forward"), so only these open a conditional there.
_IF_CLAUSE = re.compile(r"(?<![a-z0-9])(?:if|unless|in case|in the event)(?![a-z0-9])[^.!?;]*")
_ASSESSMENT = _phrases(
    "online assessment",
    "coding assessment",
    "coding challenge",
    "hackerrank",
    "codesignal",
    "codility",
    "take home",
)
_CONFIRMATION = _phrases(
    "thank you for applying",
    "thanks for applying",
    "application received",
    "received your application",
    "application has been received",
    "thanks for your interest",
    "thank you for your interest",
    "thank you for your application",
    "application has been submitted",
)

_RECRUITER_SCREEN = _phrases("phone screen", "phone screening", "recruiter", "recruiter call")
_TECHNICAL = _phrases("technical", "coding")


def normalize_text(*parts: str | None) -> str:
    """Casefold, unify apostrophes and dashes, and collapse whitespace."""
    text = " ".join(p for p in parts if p)
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"[‐-―]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_rejection(text: str) -> bool:
    # "If we decide not to move forward, we'll let you know" is a promise,
    # not a decision.
    text = _IF_CLAUSE.sub(" ", text)
    if _REJECTION.search(text) or _DECIDED_ON_OTHERS.search(text) or _REFUSED_OFFER.search(text):
        return True
    return bool(_UNFORTUNATELY.search(text)) and not _RESCHEDULE.search(text)


def _is_interview(text: str, *, assessment: bool, confirmation: bool) -> bool:
    if _SCHEDULING_LINK.search(text):
        return True
    if confirmation:
        return bool(_INTERVIEW_WITH_CONFIRMATION.search(text))
    if _INTERVIEW_STRONG.search(text):
        return True
    if assessment:
        return False
    unconditional = _INTERVIEW_PROCESS.sub(" ", _CONDITIONAL.sub(" ", text))
    if _INTERVIEW_WORD.search(unconditional):
        return True
    return bool(_NEXT_STEPS.search(unconditional))


def classify(subject: str, snippet: str) -> SuggestionKind | None:
    """The application-update kind of an email, or None when nothing matches.
    Only returns OFFER, REJECTION, INTERVIEW, ASSESSMENT or CONFIRMATION."""
    text = normalize_text(subject, snippet)
    if not text:
        return None
    if _REFUSED_OFFER.search(text):
        return SuggestionKind.REJECTION
    if _OFFER.search(text):
        return SuggestionKind.OFFER
    if _is_rejection(text):
        return SuggestionKind.REJECTION
    assessment = bool(_ASSESSMENT.search(text))
    confirmation = bool(_CONFIRMATION.search(text))
    if _is_interview(text, assessment=assessment, confirmation=confirmation):
        return SuggestionKind.INTERVIEW
    if assessment:
        return SuggestionKind.ASSESSMENT
    if confirmation:
        return SuggestionKind.CONFIRMATION
    return None


def interview_round_kind(subject: str, snippet: str) -> InterviewKind:
    """The Phase 4 round kind to prefill for an interview email. A technical
    phone screen is technical, so "technical"/"coding" is checked first."""
    text = normalize_text(subject, snippet)
    if _TECHNICAL.search(text):
        return InterviewKind.TECHNICAL
    if _RECRUITER_SCREEN.search(text):
        return InterviewKind.RECRUITER_SCREEN
    return InterviewKind.OTHER
