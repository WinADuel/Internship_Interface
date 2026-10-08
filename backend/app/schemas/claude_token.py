from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClaudeTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ClaudeTokenCreatedOut(ClaudeTokenOut):
    """The only response that ever carries the plaintext token."""

    token: str
