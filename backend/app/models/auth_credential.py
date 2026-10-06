from sqlalchemy import Boolean, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthCredential(Base):
    """A single user's login credentials: password hash and optional TOTP
    second factor. `totp_secret_encrypted` is only present once the user has
    set up 2FA; `totp_confirmed` is only true once they've verified a code
    against it (so an in-progress, unconfirmed setup can't be used to log in)."""

    __tablename__ = "auth_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
