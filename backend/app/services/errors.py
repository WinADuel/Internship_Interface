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


class ContactNotFoundError(Exception):
    """No contact exists with the requested id."""


class InvalidTransitionError(Exception):
    """The requested contact status action is not valid from the current status."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class UndoExpiredError(Exception):
    """There is no status change to undo, or the undo window has passed."""
