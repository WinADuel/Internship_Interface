import logging
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

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/docs",
    tags=["docs"],
    dependencies=[Depends(get_current_user)],
)

STATE_COOKIE = "google_oauth_state"
STATE_COOKIE_PATH = "/api/docs/google"


# The Connect Gmail flow marks its state value with this prefix. The callback
# reads the flow only from a state that matched the cookie, so the marker is
# as trustworthy as the CSRF check itself. token_urlsafe never emits ".".
GMAIL_STATE_PREFIX = "gmail."


@router.get("/google/authorize")
def google_authorize(gmail: bool = False) -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    if gmail:
        state = GMAIL_STATE_PREFIX + state
    response = RedirectResponse(
        google_docs_service.get_authorization_url(state, gmail=gmail), status_code=302
    )
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


def _finish(location: str) -> RedirectResponse:
    response = RedirectResponse(location, status_code=302)
    response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)
    return response


@router.get("/google/callback")
def google_callback(
    request: Request,
    state: str,
    code: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    expected = request.cookies.get(STATE_COOKIE)
    if not expected or not secrets.compare_digest(state.encode(), expected.encode()):
        raise HTTPException(status_code=400, detail="invalid oauth state")
    gmail = state.startswith(GMAIL_STATE_PREFIX)
    if not code:
        # Google sends ?error=access_denied (and no code) when consent is
        # cancelled, e.g. at the unverified-app screen. Nothing is stored.
        return _finish("/#/settings?gmail=0" if gmail else "/#/essays?connected=0")
    requested = google_docs_service.requested_scope(gmail)
    try:
        token_response = google_docs_service.exchange_code_for_token(code)
        scopes = google_docs_service.granted_scopes(token_response, requested)
        google_docs_service.store_token(db, token_response, scopes=scopes)
    except GoogleAuthError as exc:
        # The service scrubs its messages (status codes and exception types only,
        # never tokens or response bodies), so they are safe to log.
        logger.warning("google oauth callback failed: %s", exc)
        raise HTTPException(status_code=502, detail="google authorization failed")
    if gmail:
        granted = google_docs_service.GMAIL_SCOPE in scopes.split()
        return _finish(f"/#/settings?gmail={int(granted)}")
    return _finish("/#/essays?connected=1")


@router.get("/content")
def doc_content(doc_ref: str, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        return {"content": google_docs_service.fetch_doc_text(db, doc_ref)}
    except InvalidDocRefError:
        raise HTTPException(status_code=422, detail="invalid doc reference")
    except (GoogleDocsFetchError, GoogleNotConnectedError, GoogleAuthError) as exc:
        logger.warning("google doc fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="couldn't load doc")
