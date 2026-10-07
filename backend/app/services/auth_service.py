import threading
import time
from collections.abc import Callable

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.security import (
    decrypt_value,
    hash_password,
    match_totp_step,
    verify_password,
)
from app.models.auth_credential import AuthCredential
from app.services.errors import InvalidCredentialsError, TooManyAttemptsError

# Verified against when the username is unknown, so a miss costs the same bcrypt
# work as a hit and usernames cannot be enumerated by timing.
_DUMMY_HASH = hash_password("dummy-password")

FREE_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 300


class LoginThrottle:
    """In-process, global failed-login backoff.

    After `FREE_ATTEMPTS` consecutive failures every further failure blocks all
    logins for `min(2 ** (n - FREE_ATTEMPTS), MAX_BACKOFF_SECONDS)` seconds, where
    n is the consecutive failure count. A success resets it. The state is global
    (not per client IP) because the backend only ever sees Caddy's address, and it
    lives in process memory, which is correct for the single uvicorn worker this
    app runs. `clock` is injectable so tests are deterministic.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self.failures = 0
        self.blocked_until = 0.0

    def check(self) -> None:
        """Raise `TooManyAttemptsError` if a lockout is in effect."""
        with self._lock:
            remaining = self.blocked_until - self.clock()
        if remaining > 0:
            raise TooManyAttemptsError(remaining)

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.failures >= FREE_ATTEMPTS:
                # Clamp the exponent so a long attack never builds a huge integer.
                exponent = min(self.failures - FREE_ATTEMPTS, 20)
                delay = min(2**exponent, MAX_BACKOFF_SECONDS)
                self.blocked_until = self.clock() + delay

    def record_success(self) -> None:
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.failures = 0
            self.blocked_until = 0.0


login_throttle = LoginThrottle()


def _verify(db: Session, username: str, password: str, totp_code: str) -> None:
    credential = db.scalars(
        select(AuthCredential).where(AuthCredential.username == username)
    ).first()
    password_hash = credential.password_hash if credential else _DUMMY_HASH
    try:
        password_ok = verify_password(password, password_hash)
    except ValueError:  # malformed stored hash: an auth failure, not a 500
        password_ok = False
    if credential is None or not password_ok:
        raise InvalidCredentialsError()

    # Fail closed: an account that never confirmed its authenticator cannot log in.
    # (`python -m app.cli create-user --reset` re-enrolls it.)
    if not credential.totp_confirmed or credential.totp_secret_encrypted is None:
        raise InvalidCredentialsError()
    if not totp_code:
        raise InvalidCredentialsError()
    secret = decrypt_value(credential.totp_secret_encrypted)
    step = match_totp_step(secret, totp_code)
    if step is None:
        raise InvalidCredentialsError()
    # Replay guard: a time-step may be accepted only once and never go backwards.
    # One conditional UPDATE keeps this atomic if two logins race with the same code.
    claimed = db.execute(
        update(AuthCredential)
        .where(
            AuthCredential.id == credential.id,
            or_(AuthCredential.last_totp_step.is_(None), AuthCredential.last_totp_step < step),
        )
        .values(last_totp_step=step)
    )
    if claimed.rowcount != 1:
        raise InvalidCredentialsError()
    db.commit()


def authenticate(db: Session, username: str, password: str, totp_code: str) -> None:
    """Verify username, password and TOTP code.

    Raises `TooManyAttemptsError` (before any password hashing) during a
    lockout, and `InvalidCredentialsError` on any other failure, without
    revealing which check failed.
    """
    login_throttle.check()
    try:
        _verify(db, username, password, totp_code)
    except InvalidCredentialsError:
        login_throttle.record_failure()
        raise
    login_throttle.record_success()
