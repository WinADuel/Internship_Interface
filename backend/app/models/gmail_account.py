from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GmailAccount(Base):
    """One Gmail inbox that Gmail sync reads (Phase 7 spec §4), with its own
    encrypted refresh token (Fernet, like `oauth_tokens`), sync cursor and
    last outcome. `email` is stored lower-cased; it is null only for the
    inbox carried over from Phase 6 until its first sync reads the address.
    Deleting a row deletes its email suggestions (ON DELETE CASCADE)."""

    __tablename__ = "gmail_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    encrypted_refresh_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)
    # The newest Gmail `internalDate` (ms) handled; server-owned, never exposed.
    history_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
