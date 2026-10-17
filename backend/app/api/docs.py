import logging
import re
import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_gmail_token_client_factory
from app.core.config import settings
from app.db.session import get_db
from app.services import google_docs_service
from app.services.gmail import accounts as gmail_accounts
from app.services.gmail.client import GmailClient, GmailError
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
# Reconnect on an inbox without an address (carried over from Phase 6) also
# names that inbox: "gmail.<id>.<random>". Like the prefix, it is read only
# from a state that matched the cookie.
_INBOX_STATE = re.compile(r"^gmail\.([0-9]{1,18})\.")


@router.get("/google/authorize")
def google_authorize(gmail: bool = False, inbox: Annotated[int | None, Query(ge=1)] = None) -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    if gmail:
        state = GMAIL_STATE_PREFIX + (f"{inbox}." if inbox is not None else "") + state
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


def _inbox_address(token_response: dict, client_factory: Callable[[str], GmailClient]) -> str:
    """The new inbox's address, from Gmail's profile, read with the access
    token the consent just returned."""
    access_token = token_response.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise GoogleAuthError("google did not return an access token")
    client = client_factory(access_token)
    try:
        return client.get_profile()
    finally:
        client.close()


@router.get("/google/callback")
def google_callback(
    request: Request,
    state: str,
    code: str | None = None,
    db: Session = Depends(get_db),
    gmail_client_factory: Callable[[str], GmailClient] = Depends(get_gmail_token_client_factory),
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
        if gmail:
            # A Connect Gmail consent adds (or reconnects) one inbox and
            # never touches the Drive/Docs connection. Nothing is stored
            # when the Gmail box wasn't ticked.
            if google_docs_service.GMAIL_SCOPE not in scopes.split():
                return _finish("/#/settings?gmail=0")
            address = _inbox_address(token_response, gmail_client_factory)
            inbox = _INBOX_STATE.match(state)
            if inbox is not None:
                gmail_accounts.reconnect_unaddressed(db, int(inbox.group(1)), address, token_response, scopes)
            else:
                gmail_accounts.upsert_account(db, address, token_response, scopes)
        else:
            google_docs_service.store_token(db, token_response, scopes=scopes)
    except (GoogleAuthError, GmailError) as exc:
        # The services scrub their messages (status codes and exception types
        # only, never tokens or response bodies), so they are safe to log.
        logger.warning("google oauth callback failed: %s", exc)
        raise HTTPException(status_code=502, detail="google authorization failed")
    if gmail:
        return _finish("/#/settings?gmail=1")
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
