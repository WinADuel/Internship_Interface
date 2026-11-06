"""Auto-apply, option A: InternHelper prepares a saved posting's application
(form read from the job board, answers filled from the apply profile), the
owner reviews and edits it here, and the Chrome extension fills the real
form with those answers. The owner clicks Submit on the company's page;
nothing here submits an application."""

import base64
from collections.abc import Callable
from datetime import date, datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.apply import ApplyDraft, ApplyProfile
from app.models.posting import Posting, PostingState
from app.schemas.apply import (
    RESUME_TYPES,
    AnswerIn,
    ApplyDraftOut,
    ApplyProfileFields,
    ApplyProfileOut,
    ApplyProfileUpdate,
    ExtensionAppliedOut,
    ExtensionFillField,
    ExtensionFillOut,
    ExtensionResume,
    FormFieldOut,
    SavedAnswer,
)
from app.services.apply import forms, prefill
from app.services.apply.llm import LocalModel, LocalModelError, build_prompt, usable
from app.services.discovery import actions
from app.services.discovery.http import DiscoveryHttp
from app.services.discovery.urls import normalize_url, safe_http_url
from app.services.errors import InvalidPostingStateError, PostingNotFoundError
from app.services.settings_service import get_settings

YOU, AI = "you", "ai"


class ApplyError(Exception):
    """A user-safe reason the step couldn't be done (shown as is)."""


# --- profile -----------------------------------------------------------------------


def get_profile(db: Session) -> ApplyProfile:
    profile = db.get(ApplyProfile, 1)
    if profile is None:
        profile = ApplyProfile(id=1, fields={}, saved_answers=[])
        db.add(profile)
        db.flush()
    return profile


def profile_fields(profile: ApplyProfile) -> dict[str, str]:
    """The stored fields as a full set (fields added later read as blank)."""
    return ApplyProfileFields.model_validate(
        {k: v for k, v in (profile.fields or {}).items() if k in ApplyProfileFields.model_fields}
    ).model_dump()


def profile_out(profile: ApplyProfile) -> ApplyProfileOut:
    return ApplyProfileOut(
        fields=ApplyProfileFields.model_validate(profile_fields(profile)),
        saved_answers=[SavedAnswer.model_validate(a) for a in profile.saved_answers or []],
        resume_filename=profile.resume_filename,
        resume_uploaded_at=profile.resume_uploaded_at,
        llm_url=profile.llm_url,
        llm_model=profile.llm_model,
    )


def update_profile(db: Session, data: ApplyProfileUpdate) -> ApplyProfile:
    profile = get_profile(db)
    if data.fields is not None:
        profile.fields = data.fields.model_dump()
    if data.saved_answers is not None:
        profile.saved_answers = [a.model_dump() for a in data.saved_answers]
    if data.llm_url is not None:
        profile.llm_url = data.llm_url
    if data.llm_model is not None:
        profile.llm_model = data.llm_model
    profile.updated_at = utc_now()
    db.commit()
    return profile


def _safe_filename(name: str, content_type: str) -> str:
    base = "".join(c for c in name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if c.isalnum() or c in " ._-()").strip()
    ext = RESUME_TYPES[content_type]
    if not base.lower().endswith(ext):
        base = (base or "Resume") + ext
    return base[:120]


def set_resume(db: Session, filename: str, content_type: str, data: bytes) -> ApplyProfile:
    if content_type not in RESUME_TYPES:
        raise ApplyError("Upload your resume as a PDF or Word file")
    if not data:
        raise ApplyError("That file is empty")
    if content_type == "application/pdf" and not data.startswith(b"%PDF"):
        raise ApplyError("That file isn't a PDF")
    profile = get_profile(db)
    profile.resume_filename = _safe_filename(filename, content_type)
    profile.resume_content_type = content_type
    profile.resume_data = data
    profile.resume_uploaded_at = utc_now()
    db.commit()
    return profile


def delete_resume(db: Session) -> ApplyProfile:
    profile = get_profile(db)
    profile.resume_filename = profile.resume_content_type = None
    profile.resume_data = None
    profile.resume_uploaded_at = None
    db.commit()
    return profile


def _remember(profile: ApplyProfile, question: str, answer: str) -> None:
    saved = [a for a in profile.saved_answers or [] if prefill._norm(a.get("question", "")) != prefill._norm(question)]
    saved.insert(0, {"question": question[:500], "answer": answer})
    profile.saved_answers = saved[:200]


# --- prepared applications -----------------------------------------------------------


def _posting(db: Session, posting_id: int) -> Posting:
    posting = db.get(Posting, posting_id)
    if posting is None:
        raise PostingNotFoundError(posting_id)
    return posting


def get_draft(db: Session, posting_id: int) -> ApplyDraft | None:
    return db.scalars(select(ApplyDraft).where(ApplyDraft.posting_id == posting_id)).first()


def prepare(db: Session, http: DiscoveryHttp, posting_id: int, *, refresh: bool = False) -> ApplyDraft:
    """The posting's prepared application, reading the form the first time
    (or again with `refresh`). A re-read keeps the owner's own and the AI's
    answers for questions that are still on the form."""
    posting = _posting(db, posting_id)
    draft = get_draft(db, posting_id)
    if draft is not None and not refresh:
        return draft
    try:
        read = forms.read_form(http, posting.url)
    except forms.FormReadError as exc:
        raise ApplyError(str(exc)) from None
    form = [f.as_dict() for f in read.fields]
    profile = get_profile(db)
    answers = prefill.prefill(form, profile_fields(profile), profile.saved_answers or [], profile.resume_filename)
    if draft is not None:
        keys = {f["key"] for f in form}
        for key, answer in (draft.answers or {}).items():
            if key in keys and answer.get("source") in (YOU, AI):
                answers[key] = answer
    now = utc_now()
    if draft is None:
        draft = ApplyDraft(posting_id=posting_id)
        db.add(draft)
    draft.ats, draft.apply_url, draft.form, draft.answers = read.ats.value, read.apply_url, form, answers
    draft.fetched_at = draft.updated_at = now
    db.commit()
    return draft


def save_answers(db: Session, draft: ApplyDraft, answers: dict[str, AnswerIn]) -> ApplyDraft:
    """The owner's edits from the review page. A blank value clears the
    field; `remember` also saves a text answer for the same question on
    later applications."""
    by_key = {f["key"]: f for f in draft.form}
    unknown = [k for k in answers if k not in by_key]
    if unknown:
        raise ApplyError(f"This form has no field {unknown[0]!r}; reload the form and try again")
    current = dict(draft.answers or {})
    profile = None
    for key, answer in answers.items():
        value = answer.value
        if isinstance(value, list):
            value = [v for v in value if v]
        elif isinstance(value, str):
            value = value.strip()
        if not value:
            current.pop(key, None)
            continue
        old = current.get(key)
        source = old["source"] if old and old.get("value") == value else YOU
        current[key] = {"value": value, "source": source}
        if answer.remember and isinstance(value, str):
            profile = profile or get_profile(db)
            _remember(profile, by_key[key]["label"], value)
    draft.answers = current
    draft.updated_at = utc_now()
    db.commit()
    return draft


def draft_with_ai(
    db: Session,
    draft: ApplyDraft,
    model_factory: Callable[[str, str], LocalModel],
    keys: list[str] | None,
) -> tuple[list[str], list[str], str | None]:
    """Asks the local model for each empty open question (or just `keys`).
    Returns (drafted keys, failed keys, first error)."""
    profile = get_profile(db)
    if not profile.llm_url or not profile.llm_model:
        raise ApplyError("Set your local AI's address and model in Settings > Apply profile first")
    posting = _posting(db, draft.posting_id)
    facts = profile_fields(profile)
    background = get_settings(db).outreach_profile
    fact_view = {
        "School": facts["school"],
        "Degree": " ".join(x for x in (facts["degree"], facts["major"]) if x),
        "Graduation": " ".join(x for x in (facts["graduation_month"], facts["graduation_year"]) if x),
        "GitHub": facts["github_url"],
    }
    answers = dict(draft.answers or {})
    wanted = set(keys) if keys is not None else None
    model = model_factory(profile.llm_url, profile.llm_model)
    drafted: list[str] = []
    failed: list[str] = []
    error: str | None = None
    for field in draft.form:
        if not prefill.is_open_question(field):
            continue
        if wanted is not None and field["key"] not in wanted:
            continue
        if wanted is None and answers.get(field["key"]):
            continue
        prompt = build_prompt(
            company=posting.company,
            title=posting.title,
            question=field["label"],
            description=field.get("description", ""),
            background=background,
            facts=fact_view,
        )
        try:
            text = model.generate(prompt)
        except LocalModelError as exc:
            failed.append(field["key"])
            error = error or str(exc)
            if "reach" in str(exc) or "too long" in str(exc):
                break  # the model is down: don't wait on every question
            continue
        if usable(text):
            answers[field["key"]] = {"value": text, "source": AI}
            drafted.append(field["key"])
        else:
            failed.append(field["key"])
    draft.answers = answers
    draft.updated_at = utc_now()
    db.commit()
    return drafted, failed, error


def draft_out(db: Session, draft: ApplyDraft) -> ApplyDraftOut:
    posting = _posting(db, draft.posting_id)
    profile = get_profile(db)
    answers = draft.answers or {}
    return ApplyDraftOut(
        posting_id=posting.id,
        company=posting.company,
        title=posting.title,
        posting_state=posting.state.value,
        ats=draft.ats,
        apply_url=draft.apply_url,
        fetched_at=draft.fetched_at,
        updated_at=draft.updated_at,
        fields=[
            FormFieldOut(
                **{k: f.get(k, "") for k in ("key", "label", "kind", "section", "description")},
                required=bool(f.get("required")),
                options=f.get("options") or [],
                value=answers.get(f["key"], {}).get("value", prefill.empty_value(f)),
                source=answers.get(f["key"], {}).get("source", ""),
            )
            for f in draft.form
        ],
        resume_filename=profile.resume_filename,
        llm_ready=bool(profile.llm_url and profile.llm_model),
    )


# --- the extension ---------------------------------------------------------------------


def _find_posting(db: Session, url: str) -> Posting | None:
    safe = safe_http_url(url)
    if safe is None or normalize_url(safe) is None:
        return None
    ident = actions._identify(safe)
    rows = actions._stored(db, ident)
    if not rows and forms.job_ref(safe) is not None and safe.rstrip("/").endswith(("/apply", "/application")):
        # Lever's /apply and Ashby's /application pages: the posting is stored by its job URL.
        rows = actions._stored(db, actions._identify(safe.rstrip("/").rsplit("/", 1)[0]))
    # Prefer the posting the owner is working on.
    order = {PostingState.SAVED: 0, PostingState.APPLIED: 1, PostingState.NEW: 2, PostingState.DISMISSED: 3}
    rows.sort(key=lambda p: order.get(p.state, 9))
    return rows[0] if rows else None


def _resume(profile: ApplyProfile) -> ExtensionResume | None:
    if not profile.resume_data or not profile.resume_filename or not profile.resume_content_type:
        return None
    return ExtensionResume(
        filename=profile.resume_filename,
        content_type=profile.resume_content_type,
        data_base64=base64.b64encode(profile.resume_data).decode(),
    )


def fill_for_url(db: Session, http: DiscoveryHttp, url: str) -> ExtensionFillOut:
    profile = get_profile(db)
    base = dict(profile=profile_fields(profile), resume=_resume(profile))
    posting = _find_posting(db, url)
    if posting is None:
        return ExtensionFillOut(
            posting=None,
            ats=None,
            message="This job isn't saved in InternHelper, so only your profile fields will be filled.",
            fields=[],
            **base,
        )
    summary = {"id": posting.id, "company": posting.company, "title": posting.title, "state": posting.state.value}
    try:
        draft = prepare(db, http, posting.id)
    except ApplyError as exc:
        return ExtensionFillOut(posting=summary, ats=None, message=str(exc), fields=[], **base)
    out = draft_out(db, draft)
    return ExtensionFillOut(
        posting=summary,
        ats=draft.ats,
        message=None,
        fields=[
            ExtensionFillField(
                key=f.key,
                label=f.label,
                kind=f.kind,
                options=f.options,
                section=f.section,
                required=f.required,
                value=f.value,
            )
            for f in out.fields
        ],
        **base,
    )


def mark_applied(db: Session, url: str, today: date, now: datetime | None = None) -> ExtensionAppliedOut:
    """After the owner submits on the company's page: the posting becomes
    Applied, through the same path as the Discover page's Apply button."""
    posting = _find_posting(db, url)
    if posting is None:
        return ExtensionAppliedOut(status="not_saved", posting_id=None, application_id=None)
    if posting.state is PostingState.APPLIED and posting.application_id is not None:
        return ExtensionAppliedOut(
            status="already_applied", posting_id=posting.id, application_id=posting.application_id
        )
    try:
        application = actions.apply(db, posting.id, today, now)
    except InvalidPostingStateError:  # dismissed: the owner set it aside, so leave it
        return ExtensionAppliedOut(status="not_saved", posting_id=posting.id, application_id=None)
    return ExtensionAppliedOut(status="applied", posting_id=posting.id, application_id=application.id)
