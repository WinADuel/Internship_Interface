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


class QueueItemNotFoundError(Exception):
    """No research queue item exists with the requested id."""


class QueueItemNotPendingError(Exception):
    """The research queue item was already completed or failed."""


class AlreadyQueuedError(Exception):
    """A company-contacts queue item already exists for this application."""


class ClaudeTokenNotFoundError(Exception):
    """No Claude token exists with the requested id."""


class SheetSyncError(Exception):
    """A Google Sheets API call failed (non-2xx response or network error)."""


class PostingNotFoundError(Exception):
    """No discovered posting exists with the requested id."""


class InvalidPostingStateError(Exception):
    """The posting action is not valid from the posting's current state.
    `state` is the posting's state when one exists (e.g. "already saved")."""

    def __init__(self, message: str, state: str | None = None):
        super().__init__(message)
        self.message = message
        self.state = state


class WatchCompanyNotFoundError(Exception):
    """No watched company exists with the requested id."""


class UnsupportedCareersSiteError(Exception):
    """The careers URL is not on a job board the watchlist can read."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class DuplicateWatchCompanyError(Exception):
    """That job board is already on the watchlist."""


class InterviewRoundNotFoundError(Exception):
    """No interview round exists with the requested id."""


class StoryNotFoundError(Exception):
    """No story-bank story exists with the requested id."""


class ContactNotOnApplicationError(Exception):
    """The contact belongs to a different application than the interview round."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class StoryArchivedError(Exception):
    """An archived story can't be newly linked to an interview round."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class RoundNotScheduledError(Exception):
    """The interview round has no scheduled time (a calendar event needs one)."""


class PrepBriefNotFoundError(Exception):
    """The application has no company brief yet."""


class QueueItemWrongKindError(Exception):
    """The research queue item is of a different kind than the delivery."""
