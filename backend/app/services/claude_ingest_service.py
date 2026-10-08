"""Turns the Claude job's deliveries into contacts (spec §13.2, §13.5).

Claude-delivered content is untrusted. Only research fields and unedited
drafts are ever written on an existing contact (plus an application link a
company contact doesn't have yet); status, dates, priority, notes, archived,
origin and kind are user/app-owned.
Each ingest call commits once at the end, so a failure writes nothing."""

import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.contact import Contact, ContactKind, ContactOrigin, ContactStatus, EmailConfidence
from app.models.research_queue import QueueKind, QueueState, ResearchQueueItem
from app.schemas.claude import ContactIn, ContactsBatchIn, FollowupsBatchIn, IngestResultOut
from app.services import research_queue_service
from app.services.nudges import needs_followup_draft
from app.services.settings_service import get_settings, nudge_settings

# Research fields Claude may refresh on an existing contact (spec §13.2).
_RESEARCH_TEXT_FIELDS = (
    "title",
    "department",
    "lab_name",
    "website_url",
    "profile_url",
    "relevance_note",
    "research_summary",
    "recent_work",
)


# One plain address. Anything else (a list, a display name, URL query
# characters) could add recipients to a Gmail compose link, so it is dropped.
_SINGLE_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$*+/^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")


def is_single_email(value: str | None) -> bool:
    return bool(value) and _SINGLE_EMAIL_RE.fullmatch(value) is not None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_safe_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)


def get_work(db: Session, today: date) -> dict:
    settings = get_settings(db)
    queue = research_queue_service.pending_items(db, limit=settings.claude_job_max_items)
    active = list(
        db.scalars(select(Contact).where(Contact.archived.is_(False)).order_by(Contact.id))
    )
    nudge = nudge_settings(settings)
    return {
        "queue": [
            {"id": i.id, "kind": i.kind, "request_text": i.request_text, "target_count": i.target_count}
            for i in queue
        ],
        "outreach_profile": settings.outreach_profile,
        "known_contacts": [{"name": c.name, "organization": c.organization, "email": c.email} for c in active],
        "followups_needed": [
            {
                "contact_id": c.id,
                "name": c.name,
                "organization": c.organization,
                "draft_subject": c.draft_subject,
                "draft_body": c.draft_body,
                "sent_at": c.sent_at,
            }
            for c in active
            if needs_followup_draft(c, nudge, today)
        ],
    }


def _find_match(db: Session, item: ContactIn, email: str | None) -> Contact | None:
    if email:
        match = db.scalars(
            select(Contact).where(func.lower(Contact.email) == email.lower()).order_by(Contact.id)
        ).first()
        if match is not None:
            return match
    return db.scalars(
        select(Contact)
        .where(
            func.lower(Contact.name) == item.name.lower(),
            func.lower(Contact.organization) == item.organization.lower(),
        )
        .order_by(Contact.id)
    ).first()


def _sanitized(item: ContactIn) -> dict:
    """Research fields with unsafe URLs dropped and an unsupported "found"
    email downgraded to a guess."""
    sources = [s.model_dump() for s in item.sources if is_safe_url(s.url)]
    email = item.email if is_single_email(item.email) else None
    confidence = item.email_confidence if email else EmailConfidence.NOT_FOUND
    if confidence == EmailConfidence.FOUND and not sources:
        confidence = EmailConfidence.PATTERN_GUESS
    fields = {name: getattr(item, name) or None for name in _RESEARCH_TEXT_FIELDS}
    for url_field in ("website_url", "profile_url"):
        if not is_safe_url(fields[url_field]):
            fields[url_field] = None
    fields["email"] = email
    fields["email_confidence"] = confidence
    fields["sources"] = sources
    return fields


def _update_existing(contact: Contact, item: ContactIn, fields: dict, now: datetime) -> None:
    # A re-delivery that omits a field never erases what is already known.
    for name in _RESEARCH_TEXT_FIELDS:
        if fields[name] is not None:
            setattr(contact, name, fields[name])
    # Like the draft, the address is settled once the first email goes out: a
    # later page can't redirect the follow-up to a different recipient.
    if fields["email"] is not None and contact.status == ContactStatus.TO_CONTACT:
        contact.email = fields["email"]
        contact.email_confidence = fields["email_confidence"]
    if fields["sources"]:
        contact.sources = fields["sources"]
    # Once sent, the draft is the record of what went out (and the basis for
    # the follow-up), so it is refreshed only before sending.
    if not contact.draft_edited and contact.status == ContactStatus.TO_CONTACT and item.draft_body:
        if item.draft_subject:
            contact.draft_subject = item.draft_subject
        contact.draft_body = item.draft_body
        if contact.draft_ready_at is None:
            contact.draft_ready_at = now


def upsert_contacts(db: Session, batch: ContactsBatchIn, now: datetime | None = None) -> IngestResultOut:
    now = now or _now()
    created = updated = skipped = 0
    for item in batch.contacts:
        queue_item = db.get(ResearchQueueItem, item.queue_item_id)
        if queue_item is None or queue_item.state != QueueState.PENDING:
            skipped += 1
            continue
        fields = _sanitized(item)
        contact = _find_match(db, item, fields["email"])
        if contact is not None:
            _update_existing(contact, item, fields, now)
            # A company contact found for this application shows in its Contacts
            # section; an existing link to another application is kept.
            if (
                queue_item.kind == QueueKind.COMPANY_CONTACTS
                and contact.kind == ContactKind.COMPANY
                and contact.application_id is None
            ):
                contact.application_id = queue_item.application_id
            updated += 1
        else:
            is_company = queue_item.kind == QueueKind.COMPANY_CONTACTS
            db.add(
                Contact(
                    kind=ContactKind.COMPANY if is_company else ContactKind.PROFESSOR,
                    application_id=queue_item.application_id if is_company else None,
                    name=item.name,
                    organization=item.organization,
                    origin=ContactOrigin.CLAUDE,
                    status=ContactStatus.TO_CONTACT,
                    draft_subject=item.draft_subject or None,
                    draft_body=item.draft_body or None,
                    draft_ready_at=now if item.draft_body else None,
                    **fields,
                )
            )
            created += 1
        db.flush()  # later items in the same batch must see this one when matching
    db.commit()
    return IngestResultOut(created=created, updated=updated, skipped=skipped)


def apply_followups(db: Session, batch: FollowupsBatchIn) -> IngestResultOut:
    updated = skipped = 0
    for item in batch.followups:
        contact = db.get(Contact, item.contact_id)
        # Only active contacts awaiting a reply to the first email take a follow-up.
        if (
            contact is None
            or contact.followup_edited
            or contact.archived
            or contact.status != ContactStatus.SENT
        ):
            skipped += 1
            continue
        contact.followup_subject = item.followup_subject
        contact.followup_body = item.followup_body
        updated += 1
    db.commit()
    return IngestResultOut(created=0, updated=updated, skipped=skipped)


def complete_queue_item(db: Session, item_id: int, note: str) -> ResearchQueueItem:
    return research_queue_service.complete_item(db, item_id, note)


def fail_queue_item(db: Session, item_id: int, note: str) -> ResearchQueueItem:
    return research_queue_service.fail_item(db, item_id, note)
