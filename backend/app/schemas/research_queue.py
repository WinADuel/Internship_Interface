from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.research_queue import QueueKind, QueueState


class QueueItemCreate(BaseModel):
    kind: Literal["professor_person", "professor_search"]
    request_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    target_count: int = Field(default=1, ge=1, le=10)


class QueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: QueueKind
    request_text: str
    application_id: int | None
    target_count: int
    state: QueueState
    result_note: str | None
    created_at: datetime
    completed_at: datetime | None
