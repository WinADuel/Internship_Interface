from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_sheets_client_factory
from app.db.session import get_db
from app.schemas.claude_token import ClaudeTokenCreatedOut, ClaudeTokenOut
from app.schemas.settings import SettingsOut, SettingsUpdate, SheetSyncOut
from app.models.app_settings import AppSettings
from app.services import (
    claude_token_service,
    google_docs_service,
    settings_service,
    sheet_sync_service,
)
from app.services.errors import ClaudeTokenNotFoundError

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)


def _settings_out(db: Session, row: AppSettings) -> SettingsOut:
    return SettingsOut.model_validate(row).model_copy(
        update={
            "google_connected": google_docs_service.is_google_connected(db),
            "gmail_granted": google_docs_service.is_gmail_granted(db),
        }
    )


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return _settings_out(db, settings_service.get_settings(db))


@router.patch("", response_model=SettingsOut)
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    return _settings_out(db, settings_service.update_settings(db, data))


@router.get("/claude-tokens", response_model=list[ClaudeTokenOut])
def list_claude_tokens(db: Session = Depends(get_db)):
    return claude_token_service.list_tokens(db)


@router.post("/claude-tokens", response_model=ClaudeTokenCreatedOut, status_code=201)
def create_claude_token(db: Session = Depends(get_db)):
    token, raw = claude_token_service.create_token(db)
    return ClaudeTokenCreatedOut(**ClaudeTokenOut.model_validate(token).model_dump(), token=raw)


@router.post("/claude-tokens/{token_id}/revoke", response_model=ClaudeTokenOut)
def revoke_claude_token(token_id: int, db: Session = Depends(get_db)):
    try:
        return claude_token_service.revoke_token(db, token_id)
    except ClaudeTokenNotFoundError:
        raise HTTPException(status_code=404, detail="claude token not found")


@router.post("/sheet-sync", response_model=SheetSyncOut)
def sync_sheet_now(
    db: Session = Depends(get_db),
    client_factory: Callable = Depends(get_sheets_client_factory),
):
    ok = sheet_sync_service.safe_sync(db, client_factory, sheet_sync_service.ALL_TABS)
    settings = settings_service.get_settings(db)
    return SheetSyncOut(
        ok=ok,
        last_sheet_sync_at=settings.last_sheet_sync_at,
        last_sheet_sync_error=settings.last_sheet_sync_error,
        sheet_url=sheet_sync_service.sheet_url(settings.backup_sheet_id),
    )
