from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.db.session import SessionLocal, get_db
from app.models.auth_credential import AuthCredential
from app.models.claude_token import ClaudeToken
from app.services import claude_token_service
from app.services.backup.dump import run_dump
from app.services.discovery.http import DiscoveryHttp, HttpxDiscoveryHttp
from app.services.gmail.client import GmailClient, GoogleGmailClient
from app.services.gmail.sync import GmailClientFactory, google_gmail_client
from app.services.sheet_sync_service import SheetSyncScheduler, google_sheets_client
from app.services.sheets_client import SheetsClient


def get_current_user(request: Request, db: Session = Depends(get_db)) -> AuthCredential:
    """Resolve the logged-in user from the `access_token` cookie, or raise 401."""
    unauthorized = HTTPException(status_code=401, detail="not authenticated")
    token = request.cookies.get("access_token")
    if not token:
        raise unauthorized
    try:
        payload = decode_token(token, expected_type=ACCESS_TOKEN_TYPE)
    except jwt.PyJWTError:
        raise unauthorized
    user = db.scalars(
        select(AuthCredential).where(AuthCredential.username == payload["sub"])
    ).first()
    if user is None:
        raise unauthorized
    return user


def get_claude_token(request: Request, db: Session = Depends(get_db)) -> ClaudeToken:
    """Authenticate the scheduled Claude job by `Authorization: Bearer` only.
    Cookies are never consulted, so a browser session can't reach
    /api/claude/*, and cookie routes never read this header (spec §13.5)."""
    unauthorized = HTTPException(status_code=401, detail="invalid claude token")
    scheme, _, raw = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        raise unauthorized
    token = claude_token_service.authenticate(db, raw.strip())
    if token is None:
        raise unauthorized
    return token


def get_sheet_sync_scheduler() -> SheetSyncScheduler:
    """Overridden in tests with a recorder."""
    return SheetSyncScheduler()


def get_sheets_client_factory() -> Callable[[Session], SheetsClient]:
    """Builds the Sheets client for a synchronous "Sync now"; overridden in tests."""
    return google_sheets_client


def get_discovery_http() -> DiscoveryHttp:
    """The only way discovery routes reach the network; overridden in tests."""
    return HttpxDiscoveryHttp()


def get_scan_session_factory() -> Callable[[], AbstractContextManager[Session]]:
    """Opens the session Scan now's background task runs in (the request's
    session is closed by then). `with factory() as db:` closes it on exit.
    Overridden in tests so the scan runs inside the test transaction."""
    return SessionLocal


def get_backup_dump() -> Callable[..., Path]:
    """Takes the dump for Back up now (pg_dump); overridden in tests."""
    return run_dump


def get_gmail_client_factory() -> GmailClientFactory:
    """Builds the Gmail client for Sync now; overridden in tests."""
    return google_gmail_client


def get_gmail_token_client_factory() -> Callable[[str], GmailClient]:
    """Builds a Gmail client from a new access token, for the Connect Gmail
    callback's profile lookup (the inbox's address); overridden in tests."""
    return GoogleGmailClient
