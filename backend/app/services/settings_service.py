from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.schemas.settings import SettingsUpdate
from app.services.nudges import NudgeSettings

SETTINGS_ID = 1


def get_settings(db: Session) -> AppSettings:
    """Return the single settings row, creating it with defaults on first use."""
    settings = db.get(AppSettings, SETTINGS_ID)
    if settings is None:
        settings = AppSettings(id=SETTINGS_ID)
        db.add(settings)
        db.commit()
    return settings


def update_settings(db: Session, data: SettingsUpdate) -> AppSettings:
    settings = get_settings(db)
    for name, value in data.model_dump(exclude_unset=True).items():
        setattr(settings, name, value)
    db.commit()
    return settings


def nudge_settings(s: AppSettings) -> NudgeSettings:
    return NudgeSettings(
        unsent_days=s.nudge_unsent_days,
        followup_days=s.nudge_followup_days,
        gone_quiet_days=s.nudge_gone_quiet_days,
        replied_stale_days=s.nudge_replied_stale_days,
    )
