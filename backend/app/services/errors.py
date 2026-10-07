class InvalidCredentialsError(Exception):
    """Login failed: wrong username, password, or TOTP code."""


class TooManyAttemptsError(Exception):
    """Login is temporarily locked out after repeated failures."""

    def __init__(self, retry_after: float):
        super().__init__("too many attempts")
        self.retry_after = retry_after


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
