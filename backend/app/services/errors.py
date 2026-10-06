class InvalidCredentialsError(Exception):
    """Login failed: wrong username, password, or TOTP code."""


class TotpAlreadyConfirmedError(Exception):
    """TOTP setup was requested but a confirmed secret already exists."""


class InvalidTotpCodeError(Exception):
    """A TOTP code did not match the pending secret."""


class ApplicationNotFoundError(Exception):
    """No application exists with the requested id."""


class GoogleAuthError(Exception):
    """Google OAuth failed or the app is not connected to Google."""
