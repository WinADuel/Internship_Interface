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


class GoogleNotConnectedError(Exception):
    """No Google token is stored, so docs cannot be fetched."""


class GoogleDocsFetchError(Exception):
    """Fetching a Google Doc failed (non-2xx response or network error)."""


class InvalidDocRefError(Exception):
    """The doc reference is not a valid Drive file id or docs.google.com URL."""
