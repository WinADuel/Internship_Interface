"""Auto-apply routes for the app (session cookie): the apply profile and
resume, the extension's tokens, and each saved posting's prepared
application. The work is in `app.services.apply.service`."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_discovery_http, get_local_model_factory
from app.db.session import get_db
from app.schemas.apply import (
    MAX_RESUME_BYTES,
    AnswersIn,
    ApplyDraftOut,
    ApplyProfileOut,
    ApplyProfileUpdate,
    DraftAiIn,
    DraftAiOut,
    ExtensionTokenCreatedOut,
    ExtensionTokenOut,
)
from app.services.apply import service, tokens
from app.services.apply.llm import LocalModel
from app.services.discovery.http import DiscoveryHttp
from app.services.errors import ExtensionTokenNotFoundError, PostingNotFoundError

router = APIRouter(prefix="/api/apply", tags=["apply"], dependencies=[Depends(get_current_user)])


def _bad(exc: service.ApplyError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _posting_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="posting not found")


# --- profile -------------------------------------------------------------------------


@router.get("/profile", response_model=ApplyProfileOut)
def get_profile(db: Session = Depends(get_db)):
    profile = service.get_profile(db)
    db.commit()
    return service.profile_out(profile)


@router.patch("/profile", response_model=ApplyProfileOut)
def update_profile(data: ApplyProfileUpdate, db: Session = Depends(get_db)):
    return service.profile_out(service.update_profile(db, data))


@router.put("/profile/resume", response_model=ApplyProfileOut)
async def upload_resume(
    request: Request,
    filename: str = Query(min_length=1, max_length=300),
    db: Session = Depends(get_db),
):
    """The file is the raw request body, with its own Content-Type."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="Your resume must be 5 MB or smaller")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_RESUME_BYTES:
            raise HTTPException(status_code=413, detail="Your resume must be 5 MB or smaller")
    try:
        profile = service.set_resume(db, filename, content_type, bytes(data))
    except service.ApplyError as exc:
        raise _bad(exc) from None
    return service.profile_out(profile)


@router.delete("/profile/resume", response_model=ApplyProfileOut)
def delete_resume(db: Session = Depends(get_db)):
    return service.profile_out(service.delete_resume(db))


# --- extension tokens ----------------------------------------------------------------


@router.get("/extension-tokens", response_model=list[ExtensionTokenOut])
def list_extension_tokens(db: Session = Depends(get_db)):
    return tokens.list_tokens(db)


@router.post("/extension-tokens", response_model=ExtensionTokenCreatedOut, status_code=201)
def create_extension_token(db: Session = Depends(get_db)):
    token, raw = tokens.create_token(db)
    return ExtensionTokenCreatedOut(**ExtensionTokenOut.model_validate(token).model_dump(), token=raw)


@router.post("/extension-tokens/{token_id}/revoke", response_model=ExtensionTokenOut)
def revoke_extension_token(token_id: int, db: Session = Depends(get_db)):
    try:
        return tokens.revoke_token(db, token_id)
    except ExtensionTokenNotFoundError:
        raise HTTPException(status_code=404, detail="token not found") from None


# --- prepared applications -----------------------------------------------------------


@router.get("/postings/{posting_id}", response_model=ApplyDraftOut)
def get_application(
    posting_id: int,
    refresh: bool = False,
    db: Session = Depends(get_db),
    http: DiscoveryHttp = Depends(get_discovery_http),
):
    """The prepared application, reading the job board's form the first
    time (or again with `refresh=true`)."""
    try:
        draft = service.prepare(db, http, posting_id, refresh=refresh)
    except PostingNotFoundError:
        raise _posting_not_found() from None
    except service.ApplyError as exc:
        raise _bad(exc) from None
    return service.draft_out(db, draft)


def _draft(db: Session, posting_id: int):
    draft = service.get_draft(db, posting_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="this posting's application hasn't been prepared yet")
    return draft


@router.put("/postings/{posting_id}/answers", response_model=ApplyDraftOut)
def save_answers(posting_id: int, body: AnswersIn, db: Session = Depends(get_db)):
    draft = _draft(db, posting_id)
    try:
        service.save_answers(db, draft, body.answers)
    except service.ApplyError as exc:
        raise _bad(exc) from None
    return service.draft_out(db, draft)


@router.post("/postings/{posting_id}/draft-ai", response_model=DraftAiOut)
def draft_with_ai(
    posting_id: int,
    body: DraftAiIn,
    db: Session = Depends(get_db),
    model_factory: Callable[[str, str], LocalModel] = Depends(get_local_model_factory),
):
    draft = _draft(db, posting_id)
    try:
        drafted, failed, error = service.draft_with_ai(db, draft, model_factory, body.keys)
    except service.ApplyError as exc:
        raise _bad(exc) from None
    return DraftAiOut(drafted=drafted, failed=failed, error=error, draft=service.draft_out(db, draft))
