from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.schemas.claude_token import ClaudeTokenCreatedOut, ClaudeTokenOut
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services import claude_token_service, settings_service
from app.services.errors import ClaudeTokenNotFoundError

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return settings_service.get_settings(db)


@router.patch("", response_model=SettingsOut)
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    return settings_service.update_settings(db, data)


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
