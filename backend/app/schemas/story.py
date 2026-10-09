from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

# Caps from the Phase 4 spec §3.
MAX_TAGS = 15
MAX_TAG_LENGTH = 40

StoryTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
StarText = Annotated[str, StringConstraints(max_length=5_000)]

_NON_NULLABLE_FIELDS = ("title", "tags", "archived")


def normalize_tags(tags: list[str]) -> list[str]:
    """Trimmed, lower-cased, blanks dropped and duplicates removed (first
    occurrence kept), so tag filters match however a tag was typed."""
    out: list[str] = []
    for raw in tags:
        tag = raw.strip().lower()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"tags must be at most {MAX_TAG_LENGTH} characters")
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise ValueError(f"at most {MAX_TAGS} tags")
    return out


class StoryCreate(BaseModel):
    title: StoryTitle
    situation: StarText | None = None
    task: StarText | None = None
    action: StarText | None = None
    result: StarText | None = None
    tags: list[str] = []

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        return normalize_tags(value)


class StoryUpdate(BaseModel):
    """Omitted means unchanged; `archived` hides a story from the bank."""

    title: StoryTitle | None = None
    situation: StarText | None = None
    task: StarText | None = None
    action: StarText | None = None
    result: StarText | None = None
    tags: list[str] | None = None
    archived: bool | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_tags(value)

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "StoryUpdate":
        bad = [f for f in _NON_NULLABLE_FIELDS if f in self.model_fields_set and getattr(self, f) is None]
        if bad:
            raise ValueError(f"{', '.join(bad)} cannot be null")
        return self


class StoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    situation: str | None
    task: str | None
    action: str | None
    result: str | None
    tags: list[str]
    archived: bool
    created_at: datetime
    updated_at: datetime
