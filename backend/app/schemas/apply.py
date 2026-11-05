"""Request and response models for auto-apply."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.services.discovery.urls import safe_http_url

Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
YesNo = Literal["", "yes", "no"]
Demographic = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]

MAX_SAVED_ANSWERS = 200
MAX_ANSWER = 10_000
MAX_RESUME_BYTES = 5 * 1024 * 1024
RESUME_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


class ApplyProfileFields(BaseModel):
    """The standard answers. Every field is optional; a blank one is left
    for the owner to fill on the form. Demographic answers are free text
    matched to each form's options: "decline" picks the "I don't wish to
    answer" option; blank leaves the question alone."""

    model_config = ConfigDict(extra="forbid")

    first_name: Short = ""
    last_name: Short = ""
    preferred_name: Short = ""
    email: Short = ""
    phone: Short = ""
    city: Short = ""
    state: Short = ""
    country: Short = ""
    linkedin_url: Short = ""
    github_url: Short = ""
    website_url: Short = ""
    current_company: Short = ""
    school: Short = ""
    degree: Short = ""
    major: Short = ""
    gpa: Short = ""
    graduation_month: Short = ""
    graduation_year: Short = ""
    work_authorized: YesNo = ""
    needs_sponsorship: YesNo = ""
    willing_to_relocate: YesNo = ""
    how_heard: Short = ""
    pronouns: Short = ""
    gender: Demographic = ""
    race: Demographic = ""
    hispanic_latino: Demographic = ""
    veteran: Demographic = ""
    disability: Demographic = ""
    lgbtq: Demographic = ""


class SavedAnswer(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    answer: Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_ANSWER)]


def _llm_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    safe = safe_http_url(value)
    if safe is None:
        raise ValueError("enter an http:// or https:// address, like http://192.168.1.20:11434")
    return safe.rstrip("/")


class ApplyProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: ApplyProfileFields | None = None
    saved_answers: Annotated[list[SavedAnswer], Field(max_length=MAX_SAVED_ANSWERS)] | None = None
    llm_url: Annotated[str, StringConstraints(max_length=500)] | None = None
    llm_model: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None

    @field_validator("llm_url")
    @classmethod
    def _check_llm_url(cls, value: str | None) -> str | None:
        return None if value is None else _llm_url(value)


class ApplyProfileOut(BaseModel):
    fields: ApplyProfileFields
    saved_answers: list[SavedAnswer]
    resume_filename: str | None
    resume_uploaded_at: datetime | None
    llm_url: str
    llm_model: str


class FormFieldOut(BaseModel):
    key: str
    label: str
    kind: str
    required: bool
    options: list[dict[str, str]]
    section: str
    description: str
    value: str | list[str]
    source: str


class ApplyDraftOut(BaseModel):
    posting_id: int
    company: str
    title: str
    posting_state: str
    ats: str
    apply_url: str
    fetched_at: datetime
    updated_at: datetime
    fields: list[FormFieldOut]
    resume_filename: str | None
    llm_ready: bool


class AnswerIn(BaseModel):
    value: Annotated[str, StringConstraints(max_length=MAX_ANSWER)] | Annotated[
        list[Annotated[str, StringConstraints(max_length=500)]], Field(max_length=200)
    ]
    # Saves a text answer as a reusable answer for this question's label.
    remember: bool = False


class AnswersIn(BaseModel):
    answers: Annotated[dict[str, AnswerIn], Field(max_length=200)]


class DraftAiIn(BaseModel):
    # The fields to draft; omitted means every empty open question.
    keys: Annotated[list[str], Field(max_length=100)] | None = None


class DraftAiOut(BaseModel):
    drafted: list[str]
    failed: list[str]
    error: str | None
    draft: ApplyDraftOut


class ExtensionTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ExtensionTokenCreatedOut(ExtensionTokenOut):
    token: str


class ExtensionUrlIn(BaseModel):
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ExtensionFillField(BaseModel):
    key: str
    label: str
    kind: str
    options: list[dict[str, str]]
    section: str
    required: bool
    value: str | list[str]


class ExtensionResume(BaseModel):
    filename: str
    content_type: str
    data_base64: str


class ExtensionFillOut(BaseModel):
    """What the extension fills. `posting` is None when the page's job isn't
    saved in InternHelper; the profile then still fills the standard fields."""

    posting: dict[str, Any] | None
    ats: str | None
    message: str | None
    fields: list[ExtensionFillField]
    profile: dict[str, str]
    resume: ExtensionResume | None


class ExtensionAppliedOut(BaseModel):
    status: Literal["applied", "already_applied", "not_saved"]
    posting_id: int | None
    application_id: int | None
