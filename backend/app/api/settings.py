from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services import settings_service

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
