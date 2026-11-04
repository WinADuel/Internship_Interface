"""Time helpers shared across the app. A leaf module: it imports nothing from
the app, so any layer can use it."""

from datetime import UTC, datetime
from typing import overload


def utc_now() -> datetime:
    """The current time, time-zone aware, in UTC."""
    return datetime.now(UTC)


@overload
def as_utc(value: datetime) -> datetime: ...
@overload
def as_utc(value: None) -> None: ...
def as_utc(value: datetime | None) -> datetime | None:
    """A naive datetime read as UTC; an aware one (or None) as given."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
