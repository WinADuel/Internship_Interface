from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.application import ApplicationStatus, Priority


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
