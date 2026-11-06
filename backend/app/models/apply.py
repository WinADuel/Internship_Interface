"""Auto-apply (option A): the owner's apply profile, one prepared
application per posting, and the Chrome extension's bearer tokens.

Nothing here submits anything. InternHelper prepares the answers; the
extension fills the real form in the owner's browser; the owner clicks
Submit."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApplyProfile(Base):
    """Single row (id = 1): the standard answers every application asks for,
    reusable answers to recurring questions, the resume file and the local
    AI model's address."""

    __tablename__ = "apply_profile"
    __table_args__ = (CheckConstraint("id = 1", name="apply_profile_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1, autoincrement=False)
    # Field name -> string (see schemas.apply.ApplyProfileFields).
    fields: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # [{"question": ..., "answer": ...}], matched to form labels.
    saved_answers: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    resume_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    resume_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Ollama on the owner's own machine, e.g. http://192.168.1.20:11434.
    llm_url: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    llm_model: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApplyDraft(Base):
    """A posting's application form as the job board publishes it, and the
    answers the owner approved for it."""

    __tablename__ = "apply_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int] = mapped_column(
        ForeignKey("postings.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    ats: Mapped[str] = mapped_column(Text, nullable=False)
    apply_url: Mapped[str] = mapped_column(Text, nullable=False)
    # [FormField as a dict] (services.apply.forms.FormField).
    form: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Field key -> {"value": str | [str], "source": "profile" | "saved" | "ai" | "you"}.
    answers: Mapped[dict[str, dict]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExtensionToken(Base):
    """A revocable bearer token for the InternHelper Chrome extension. Only
    the SHA-256 hash is stored; the plaintext is shown once at creation."""

    __tablename__ = "extension_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
