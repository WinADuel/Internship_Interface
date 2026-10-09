from datetime import UTC, datetime

import pytest

from app.models.contact import ContactStatus
from app.services.gmail.classify import SuggestionKind
from app.services.gmail.matching import (
    ApplicationRef,
    ContactRef,
    Direction,
    EmailHeaders,
    Proposal,
    Snapshot,
    company_key,
    extract_role,
    is_ats_sender,
    match_application,
    match_contact,
    propose,
)

K = SuggestionKind
WHEN = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _at(day: int) -> datetime:
    return datetime(2026, 9, day, tzinfo=UTC)


APPS = (
    ApplicationRef(1, "Stripe, Inc.", "Software Engineering Intern", "applied", False, _at(1)),
    ApplicationRef(2, "Stripe", "Data Science Intern", "applied", False, _at(5)),
    ApplicationRef(3, "Box", "Software Engineer Intern", "applied", False, _at(2)),
    ApplicationRef(4, "Square", "iOS Intern", "wishlist", False, _at(2)),
    ApplicationRef(5, "Jane Street", "Software Engineer Intern", "applied", False, _at(2)),
    ApplicationRef(6, "Palantir Technologies", "Forward Deployed Intern", "interview", False, _at(2)),
    ApplicationRef(7, "Apple", "Hardware Intern", "applied", False, _at(2)),
    ApplicationRef(8, "Old Corp", "Intern", "rejected", True, _at(2)),
    ApplicationRef(9, "Nvidia", "Deep Learning Intern", "applied", False, _at(2)),
    ApplicationRef(10, "LinkedIn", "SWE Intern", "applied", False, _at(2)),
    ApplicationRef(11, "X", "Intern", "applied", False, _at(2)),
)
CONTACTS = (
    ContactRef(21, "Jane.Recruiter@stripe.com", "sent", 1),
    ContactRef(22, "prof.lee@mit.edu", "followed_up", None),
    ContactRef(23, "sam@ramp.com", "to_contact", None),
    ContactRef(24, "done@box.com", "replied", 3),
    ContactRef(25, None, "sent", None),
    ContactRef(26, "dup@acme.com", "to_contact", None),
    ContactRef(27, "dup@acme.com", "sent", None),
    ContactRef(28, "ann@stripe.com", "sent", None),
    ContactRef(29, "bo@box.com", "sent", 8),
)
SNAPSHOT = Snapshot(applications=APPS, contacts=CONTACTS)


def inbound(from_name, from_email, subject, snippet=""):
    return EmailHeaders(Direction.INBOUND, from_name, from_email, subject, snippet, WHEN)


def sent(to, subject="Hello", cc=()):
    return EmailHeaders(
        Direction.SENT, "Me", "me@gmail.com", subject, "", WHEN, to_emails=tuple(to), cc_emails=tuple(cc)
    )


CASES = [
    # --- contacts (§4.1)
    ("contact reply", inbound("Jane", "jane.recruiter@STRIPE.com", "Re: coffee chat", "Sure, happy to chat"),
     Proposal(K.CONTACT_REPLY, application_id=1, contact_id=21)),
    ("followed-up contact replies", inbound("Prof. Lee", "Prof.Lee@mit.edu", "Re: research", "Thanks for reaching out"),
     Proposal(K.CONTACT_REPLY, contact_id=22)),
    ("contact reply beats classification", inbound("Jane", "jane.recruiter@stripe.com", "Re: chat", "Unfortunately I'm out this week"),
     Proposal(K.CONTACT_REPLY, application_id=1, contact_id=21)),
    # A contact's reply that is an application update becomes that kind, for
    # the contact's application, keeping the contact (progress-log ruling).
    ("contact sends a rejection", inbound("Jane", "jane.recruiter@stripe.com", "Re: your application", "Unfortunately we will not be moving forward"),
     Proposal(K.REJECTION, application_id=1, contact_id=21)),
    ("contact invites to interview", inbound("Jane", "jane.recruiter@stripe.com", "Re: coffee chat", "Could you share your availability for an interview?"),
     Proposal(K.INTERVIEW, application_id=1, contact_id=21)),
    ("contact sends an offer", inbound("Jane", "jane.recruiter@stripe.com", "Offer letter", "We're pleased to offer you the internship"),
     Proposal(K.OFFER, application_id=1, contact_id=21)),
    ("contact sends an assessment", inbound("Jane", "jane.recruiter@stripe.com", "Re: next steps", "Here is the HackerRank coding challenge"),
     Proposal(K.ASSESSMENT, application_id=1, contact_id=21)),
    ("contact confirmation stays a reply", inbound("Jane", "jane.recruiter@stripe.com", "Re: hi", "Thanks for applying! We received your application"),
     Proposal(K.CONTACT_REPLY, application_id=1, contact_id=21)),
    ("contact asking availability for coffee stays a reply", inbound("Jane", "jane.recruiter@stripe.com", "Re: coffee chat", "Sure, what's your availability next week?"),
     Proposal(K.CONTACT_REPLY, application_id=1, contact_id=21)),
    ("unattached contact: the sender's company", inbound("Ann", "ann@stripe.com", "Re: Data Science Intern role", "Unfortunately we will not be moving forward"),
     Proposal(K.REJECTION, application_id=2, contact_id=28)),
    ("unattached contact at an untracked place stays a reply", inbound("Prof. Lee", "prof.lee@mit.edu", "Re: research position", "Unfortunately the position is filled"),
     Proposal(K.CONTACT_REPLY, contact_id=22)),
    ("contact of an archived application: the sender's company", inbound("Bo", "bo@box.com", "Re: Box internship", "Unfortunately we will not be moving forward"),
     Proposal(K.REJECTION, application_id=3, contact_id=29)),
    ("sent to to_contact", sent(["Sam@Ramp.com"]), Proposal(K.CONTACT_SENT, contact_id=23)),
    ("sent with contact on cc", sent(["someone@else.com"], cc=["sam@ramp.com"]), Proposal(K.CONTACT_SENT, contact_id=23)),
    ("sent to contact already sent", sent(["jane.recruiter@stripe.com"]), None),
    ("sent to unknown", sent(["friend@gmail.com"], subject="Thank you for applying"), None),
    ("duplicate contact email: eligible one", inbound("Dup", "dup@acme.com", "Re: hi"), Proposal(K.CONTACT_REPLY, contact_id=27)),
    ("duplicate contact email: sent", sent(["dup@acme.com"]), Proposal(K.CONTACT_SENT, contact_id=26)),
    # An already-replied contact falls through to the application match.
    ("replied contact, then company mail", inbound("Done", "done@box.com", "Interview with Box", "Please share your availability for the intern interview"),
     Proposal(K.INTERVIEW, application_id=3)),
    # --- direct company mail (§4.2)
    ("company domain confirmation", inbound("Stripe", "no-reply@stripe.com", "Thanks for applying to Stripe!", "We received your application for Data Science Intern"),
     Proposal(K.CONFIRMATION, application_id=2)),
    ("role title picks the application", inbound("Stripe Recruiting", "recruiting@stripe.com", "Your Software Engineering Intern application", "Unfortunately we will not be moving forward"),
     Proposal(K.REJECTION, application_id=1)),
    ("no role: most recently updated", inbound("Stripe", "jobs@mail.stripe.com", "Interview invitation", "We'd like to invite you to interview"),
     Proposal(K.INTERVIEW, application_id=2)),
    ("two-word company in domain", inbound("Jane Street Recruiting", "recruiting@janestreet.com", "Jane Street - next steps", "We'd like to schedule a call"),
     Proposal(K.INTERVIEW, application_id=5)),
    ("suffix removed", inbound("Palantir", "talent@palantir.com", "Offer letter", "We're pleased to offer you the internship"),
     Proposal(K.OFFER, application_id=6)),
    ("display name, personal address", inbound("Box Recruiting", "recruiter.box@gmail.com", "Box internship", "Thank you for applying!"),
     Proposal(K.CONFIRMATION, application_id=3)),
    ("Square via its own domain name", inbound("Square", "careers@squareup.com", "Your iOS Intern application", "Thank you for applying to Square"),
     Proposal(K.CONFIRMATION, application_id=4)),
    ("archived application ignored", inbound("Old Corp", "hr@oldcorp.com", "Your application", "Unfortunately we filled the role"), None),
    ("job mail with no kind", inbound("Stripe", "no-reply@stripe.com", "Complete your candidate profile", "Log in to finish"), None),
    # --- false-positive traps
    ("Dropbox is not Box", inbound("Dropbox", "no-reply@dropbox.com", "Thank you for applying", "We received your application"), None),
    ("inbox is not Box", inbound("Inbox Weekly", "news@inbox.com", "Interview tips", "Ace your next interview"), None),
    ("Squarespace is not Square", inbound("Squarespace", "no-reply@squarespace.com", "Unfortunately your payment failed", ""), None),
    ("Square consumer mail", inbound("Square", "noreply@squareup.com", "Your receipt", "Unfortunately your card was declined"), None),
    ("Box marketing offer", inbound("Box", "hello@box.com", "A gift for you", "We're pleased to offer you a free trial of Box Business"), None),
    ("company hiring blast", inbound("Stripe", "news@stripe.com", "Stripe is hiring interns", "Apply now and interview this fall"), None),
    ("company marketing address", inbound("Stripe", "marketing@stripe.com", "Your application to Stripe Atlas", "Unfortunately your application is incomplete"), None),
    ("Box product next steps", inbound("Box", "no-reply@box.com", "Next steps to set up your account", ""), None),
    ("Apple order mail", inbound("Apple", "no_reply@email.apple.com", "Your order update", "Unfortunately, your order is delayed"), None),
    ("Apple recruiting mail", inbound("Apple", "no_reply@email.apple.com", "Your application", "Unfortunately we will not be moving forward"),
     Proposal(K.REJECTION, application_id=7)),
    ("marketing from unknown sender", inbound("Best Deals", "deals@shop.com", "Unfortunately, the sale ends tonight", ""), None),
    ("newsletter mentioning interview", inbound("Tech Careers Weekly", "editor@techcareers.substack.com", "5 interview tips", "How to ace your Stripe interview"), None),
    ("newsletter with company display name", inbound("The Square Deal", "squaredeal@substack.com", "Thanks for your interest", "Unfortunately the issue is late"), None),
    ("job board digest naming companies", inbound("LinkedIn Job Alerts", "jobalerts-noreply@linkedin.com", "Stripe and Box are hiring", "Interview-ready roles for you"), None),
    ("job board digest from a tracked company domain", inbound("LinkedIn", "jobs-noreply@linkedin.com", "New jobs for you", "Prepare for your next interview"), None),
    ("Handshake digest", inbound("Handshake", "noreply@joinhandshake.com", "Box is hiring interns", "Apply and get an interview"), None),
    ("tracked company on a job board", inbound("LinkedIn University Recruiting", "university@linkedin.com", "Your LinkedIn interview", "Please share your availability"),
     Proposal(K.INTERVIEW, application_id=10)),
    ("one-letter company never matches", inbound("X", "jobs@x.com", "Thank you for applying", ""), None),
    ("calendar mail from unrelated domain", inbound("Google Calendar", "calendar-notification@google.com", "Reminder", "Interview with Stripe at 2pm"), None),
    # --- applicant-tracking systems
    ("greenhouse with display name", inbound("Box", "no-reply@us.greenhouse-mail.io", "Thank you for applying to Box", ""),
     Proposal(K.CONFIRMATION, application_id=3)),
    ("lever, role picks", inbound("Stripe", "no-reply@hire.lever.co", "Stripe | Data Science Intern", "Your availability for a phone screen"),
     Proposal(K.INTERVIEW, application_id=2)),
    ("workday tenant address", inbound("Workday", "nvidia@myworkday.com", "Application received", "Thank you for applying"),
     Proposal(K.CONFIRMATION, application_id=9)),
    ("ats with generic name searches subject", inbound("no-reply", "no-reply@ashbyhq.com", "Your application to Jane Street", "Thanks for your interest in Jane Street"),
     Proposal(K.CONFIRMATION, application_id=5)),
    ("box-the-word in another company's ATS mail", inbound("Rivian", "no-reply@greenhouse.io", "Thank you for applying to Rivian", "Check the box below to confirm your email"),
     Proposal(K.NEW_APPLICATION, proposed_company="Rivian")),
    ("new application with role", inbound("Rivian Recruiting", "no-reply@hire.lever.co", "Thank you for applying", "Thanks for applying to the Software Intern position at Rivian"),
     Proposal(K.NEW_APPLICATION, proposed_company="Rivian", proposed_role="Software Intern")),
    ("new application from interview", inbound("Hiring Team at Figma", "no-reply@ashbyhq.com", "Figma interview", "Please share your availability"),
     Proposal(K.NEW_APPLICATION, proposed_company="Figma")),
    ("untracked rejection is dropped", inbound("Rivian", "no-reply@greenhouse.io", "Your application", "Unfortunately we will not be moving forward"), None),
    ("ats self-branded mail", inbound("Greenhouse", "no-reply@greenhouse.io", "Thank you for applying", ""), None),
    ("ats mail with no kind", inbound("Rivian", "no-reply@greenhouse.io", "Verify your email", "Confirm your account"), None),
    ("archived company is new again", inbound("Old Corp", "no-reply@greenhouse.io", "Thank you for applying to Old Corp", ""),
     Proposal(K.NEW_APPLICATION, proposed_company="Old Corp")),
    ("short tracked name is not proposed as new", inbound("X Recruiting", "no-reply@greenhouse.io", "Thank you for applying", ""), None),
]


@pytest.mark.parametrize(("headers", "expected"), [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_propose(headers, expected):
    assert propose(headers, SNAPSHOT) == expected


def test_contact_statuses_accept_enum_members():
    contacts = [ContactRef(1, "a@b.com", ContactStatus.FOLLOWED_UP, None)]
    assert match_contact(inbound("A", "a@b.com", "Re: hi"), contacts) == Proposal(K.CONTACT_REPLY, contact_id=1)


@pytest.mark.parametrize("status", ["to_contact", "replied", "meeting", "accepted", "declined"])
def test_inbound_contact_needs_sent_or_followed_up(status):
    assert match_contact(inbound("A", "a@b.com", "Re: hi"), [ContactRef(1, "a@b.com", status, None)]) is None


def test_match_application_ignores_sent_mail():
    headers = sent(["recruiting@stripe.com"], subject="Thank you for applying")
    assert match_application(headers, APPS) is None


def test_propose_with_empty_snapshot():
    assert propose(inbound("Stripe", "no-reply@stripe.com", "Thanks for applying!"), Snapshot()) is None


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Stripe, Inc.", "stripe"),
        ("Palantir Technologies Inc", "palantir"),
        ("Jane Street", "janestreet"),
        ("AT&T", "att"),
        ("Macy's", "macys"),
        ("Nestlé", "nestle"),
        ("X", ""),
        ("HP", ""),
        ("3M", ""),
        ("", ""),
    ],
)
def test_company_key(name, key):
    assert company_key(name) == key


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("no-reply@greenhouse.io", True),
        ("no-reply@us.greenhouse-mail.io", True),
        ("x@hire.lever.co", True),
        ("nvidia@MyWorkday.com", True),
        ("x@notgreenhouse.io", False),
        ("x@greenhouse.io.evil.com", False),
        ("", False),
        (None, False),
    ],
)
def test_is_ats_sender(email, expected):
    assert is_ats_sender(email) is expected


@pytest.mark.parametrize(
    ("subject", "snippet", "role"),
    [
        ("Thank you for applying", "Thanks for applying to the Software Engineering Intern position at Rivian", "Software Engineering Intern"),
        ("Your application for Data Science Intern at Ramp", "", "Data Science Intern"),
        ("Interview", "We'd like to talk to you for our Backend Intern role", "Backend Intern"),
        ("Thank you for applying to Rivian", "We'll be in touch", None),
        ("", "", None),
    ],
)
def test_extract_role(subject, snippet, role):
    assert extract_role(subject, snippet) == role
