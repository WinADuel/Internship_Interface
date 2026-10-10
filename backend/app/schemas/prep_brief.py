from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.contact import SourceOut


class PrepBriefOut(BaseModel):
    """The Claude-written company brief. `body` and `sources` are untrusted
    plain text: the app renders them as text and links only http(s) URLs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    body: str
    sources: list[SourceOut]
    created_at: datetime
    updated_at: datetime
