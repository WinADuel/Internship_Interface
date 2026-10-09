from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.schemas.settings import SettingsUpdate
from app.services.discovery.ranking import PREF_COLUMNS, lock_scores, prefs_from_settings, rescore
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


def update_settings(db: Session, data: SettingsUpdate, now: datetime | None = None) -> AppSettings:
    """Apply the supplied fields. A change to the ranking preferences also
    stamps `ranking_updated_at` (older Claude scores become stale) and
    re-scores the Inbox and Saved postings, in the same transaction, which
    also counts as the daily re-score (`last_rescore_at`)."""
    values = data.model_dump(exclude_unset=True)
    if PREF_COLUMNS.values() & values.keys():
        # Before anything is written: the lock comes before this row's lock
        # in every transaction that takes both (see `ranking.lock_scores`).
        lock_scores(db)
    settings = get_settings(db)
    before = prefs_from_settings(settings)
    for name, value in values.items():
        setattr(settings, name, value)
    after = prefs_from_settings(settings)
    if after != before:
        now = now or datetime.now(UTC)
        settings.ranking_updated_at = now
        rescore(db, after, now)
        # Every score is now current, freshness included.
        settings.last_rescore_at = now
    db.commit()
    return settings


def nudge_settings(s: AppSettings) -> NudgeSettings:
    return NudgeSettings(
        unsent_days=s.nudge_unsent_days,
        followup_days=s.nudge_followup_days,
        gone_quiet_days=s.nudge_gone_quiet_days,
        replied_stale_days=s.nudge_replied_stale_days,
    )
