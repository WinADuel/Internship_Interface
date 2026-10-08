from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    outreach_profile: str
    nudge_unsent_days: int
    nudge_followup_days: int
    nudge_gone_quiet_days: int
    nudge_replied_stale_days: int
    claude_job_max_items: int
    backup_sheet_id: str | None
    last_sheet_sync_at: datetime | None
    last_sheet_sync_error: str | None


class SettingsUpdate(BaseModel):
    outreach_profile: str | None = Field(default=None, max_length=5000)
    nudge_unsent_days: int | None = Field(default=None, ge=1, le=90)
    nudge_followup_days: int | None = Field(default=None, ge=1, le=90)
    nudge_gone_quiet_days: int | None = Field(default=None, ge=1, le=90)
    nudge_replied_stale_days: int | None = Field(default=None, ge=1, le=90)
    claude_job_max_items: int | None = Field(default=None, ge=1, le=25)

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "SettingsUpdate":
        # Every column is NOT NULL; omitted means unchanged.
        bad = [f for f in self.model_fields_set if getattr(self, f) is None]
        if bad:
            raise ValueError(f"{', '.join(sorted(bad))} cannot be null")
        return self


class SheetSyncOut(BaseModel):
    ok: bool
    last_sheet_sync_at: datetime | None
    last_sheet_sync_error: str | None
    sheet_url: str | None
