from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.application import ApplicationStatus, Priority


_NON_NULLABLE_FIELDS = ("company", "role_title", "status", "priority")


class ApplicationCreate(BaseModel):
    company: str
    role_title: str
    date_applied: date | None = None
    status: ApplicationStatus = ApplicationStatus.WISHLIST
    job_link: str | None = None
    notes: str | None = None
    resume_version: str | None = None
    contact_person: str | None = None
    salary_range: str | None = None
    location: str | None = None
    source: str | None = None
    priority: Priority = Priority.MEDIUM
    follow_up_date: date | None = None
    interview_datetime: datetime | None = None
    google_doc_link: str | None = None


class ApplicationUpdate(BaseModel):
    company: str | None = None
    role_title: str | None = None
    date_applied: date | None = None
    status: ApplicationStatus | None = None
    job_link: str | None = None
    notes: str | None = None
    resume_version: str | None = None
    contact_person: str | None = None
    salary_range: str | None = None
    location: str | None = None
    source: str | None = None
    priority: Priority | None = None
    follow_up_date: date | None = None
    interview_datetime: datetime | None = None
    google_doc_link: str | None = None

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "ApplicationUpdate":
        # Omitted means "leave unchanged"; an explicit null on a NOT NULL
        # column would otherwise surface as a DB IntegrityError (500).
        bad = [f for f in _NON_NULLABLE_FIELDS if f in self.model_fields_set and getattr(self, f) is None]
        if bad:
            raise ValueError(f"{', '.join(bad)} cannot be null")
        return self


class ApplicationOut(ApplicationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    archived: bool
    created_at: datetime
    updated_at: datetime


class StatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    old_status: ApplicationStatus | None
    new_status: ApplicationStatus
    changed_at: datetime


class ActivityEntryOut(BaseModel):
    application_id: int
    company: str
    role_title: str
    old_status: ApplicationStatus | None
    new_status: ApplicationStatus
    changed_at: datetime
