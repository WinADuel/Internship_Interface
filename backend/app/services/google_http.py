"""Small helpers shared by the Google API clients (Gmail, Drive, Sheets).

Each client keeps its own exception type, reason table and messages; these
only read a response. Nothing from a response body is ever returned except
through a caller's fixed reason table."""

from collections.abc import Mapping

import httpx


def google_403_reason(response: httpx.Response, reasons: Mapping[str, str]) -> str | None:
    """The message in `reasons` for the first of its keys found among the
    403 response's error reasons, or None when none is (or the body isn't
    Google's error shape)."""
    try:
        errors = response.json()["error"]["errors"]
        found = {e.get("reason") for e in errors if isinstance(e, dict)}
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    for reason, message in reasons.items():
        if reason in found:
            return message
    return None


def json_object(response: httpx.Response) -> dict | None:
    """The response body as a JSON object, or None when it is not one."""
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
