import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.services import google_docs_service
from app.services.errors import (
    GoogleAuthError,
    GoogleDocsFetchError,
    GoogleNotConnectedError,
    InvalidDocRefError,
)

router = APIRouter(
    prefix="/api/docs",
    tags=["docs"],
    dependencies=[Depends(get_current_user)],
)

STATE_COOKIE = "google_oauth_state"
STATE_COOKIE_PATH = "/api/docs/google"


@router.get("/google/authorize")
def google_authorize() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(google_docs_service.get_authorization_url(state), status_code=302)
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path=STATE_COOKIE_PATH,
    )
    return response


@router.get("/google/callback")
def google_callback(
    request: Request, code: str, state: str, db: Session = Depends(get_db)
) -> RedirectResponse:
    expected = request.cookies.get(STATE_COOKIE)
    if not expected or not secrets.compare_digest(state.encode(), expected.encode()):
        raise HTTPException(status_code=400, detail="invalid oauth state")
    try:
        token_response = google_docs_service.exchange_code_for_token(code)
        google_docs_service.store_token(db, token_response, scopes=google_docs_service.GOOGLE_SCOPE)
    except GoogleAuthError:
        raise HTTPException(status_code=502, detail="google authorization failed")
    response = RedirectResponse("/#/essays?connected=1", status_code=302)
    response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)
    return response


@router.get("/content")
def doc_content(doc_ref: str, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        return {"content": google_docs_service.fetch_doc_text(db, doc_ref)}
    except InvalidDocRefError:
        raise HTTPException(status_code=422, detail="invalid doc reference")
    except (GoogleDocsFetchError, GoogleNotConnectedError, GoogleAuthError):
        raise HTTPException(status_code=502, detail="couldn't load doc")
