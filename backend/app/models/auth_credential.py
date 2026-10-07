from sqlalchemy import Boolean, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthCredential(Base):
    """A single user's login credentials: password hash and optional TOTP
    second factor. `totp_secret_encrypted` is only present once the user has
    set up 2FA; `totp_confirmed` is only true once they've verified a code
    against it (an unconfirmed account cannot log in at all)."""

    __tablename__ = "auth_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Time-step number of the last TOTP code accepted at login. A code whose
    # step is <= this value is a replay and is rejected.
    last_totp_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
