"""A minimal, read-only Gmail v1 client for the sync (Phase 6 spec §6).
Behind a Protocol so the sync's tests use a fake; the real client takes an
httpx transport so its own tests run against httpx.MockTransport.

It only ever reads the inbox's address (`users.getProfile`), lists message
ids and fetches messages with `format=metadata` and a fixed header list:
bodies, attachments and raw messages are never requested. Errors never
include tokens or response bodies."""

import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import quote

import httpx

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_PROFILE_API = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
METADATA_HEADERS = ("From", "To", "Cc", "Subject", "Date")
# Each inbox has its own token (Phase 7 spec §4): only that one needs it.
GMAIL_RECONNECT_HINT = "reconnect this inbox in Settings"
MAX_ADDRESS = 320
_TIMEOUT = httpx.Timeout(20.0)
_PAGE_SIZE = 500  # Gmail's maximum for messages.list
# Gmail message and thread ids are hex strings; anything else is refused
# before it can reach a URL path or the Open in Gmail link.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
# An inbox address as Gmail's profile gives it: no spaces, controls, quotes
# or angle brackets, one "@" with something on each side.
_ADDRESS_RE = re.compile(r"^[^\s@\x00-\x1f\x7f\"<>]+@[^\s@\x00-\x1f\x7f\"<>/]+$")
# 403 reasons that a reconnect would not fix. Only these fixed strings are
# ever shown; nothing from the response body is echoed.
_403_REASONS = {
    "rateLimitExceeded": "Gmail rate limit hit; it will retry next run",
    "userRateLimitExceeded": "Gmail rate limit hit; it will retry next run",
    "dailyLimitExceeded": "Gmail daily limit hit; it will retry next run",
}


class GmailError(Exception):
    """A Gmail call failed. `status` is the HTTP status (None for a network
    error); `reconnect` is set when only reconnecting Google can fix it."""

    def __init__(self, message: str, status: int | None = None, reconnect: bool = False):
        super().__init__(message)
        self.status = status
        self.reconnect = reconnect


@dataclass(frozen=True)
class GmailMessage:
    """A message as `format=metadata` returns it: ids, the received time
    (`internalDate`, ms since the epoch), labels, the requested headers and
    Gmail's snippet."""

    id: str
    thread_id: str
    internal_date: int
    label_ids: tuple[str, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)
    snippet: str = ""


class GmailClient(Protocol):
    def get_profile(self) -> str: ...

    def list_message_ids(self, query: str, max_ids: int) -> tuple[list[str], bool]: ...

    def get_metadata(self, message_id: str) -> GmailMessage | None: ...

    def close(self) -> None: ...


def is_gmail_id(value) -> bool:
    return isinstance(value, str) and bool(_ID_RE.fullmatch(value))


def normalize_address(value) -> str | None:
    """An inbox address, lower-cased, or None when it isn't one."""
    if not isinstance(value, str):
        return None
    address = value.strip().casefold()
    if len(address) > MAX_ADDRESS or not _ADDRESS_RE.fullmatch(address):
        return None
    return address


def _403_reason(response: httpx.Response) -> str | None:
    try:
        errors = response.json()["error"]["errors"]
        reasons = {e.get("reason") for e in errors if isinstance(e, dict)}
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    for reason, message in _403_REASONS.items():
        if reason in reasons:
            return message
    return None


class GoogleGmailClient:
    """One HTTP connection pool for the client's life; call `close()`."""

    def __init__(self, access_token: str, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            transport=transport,
            timeout=_TIMEOUT,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, op: str, url: str, params, *, allow_404: bool = False) -> httpx.Response | None:
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise GmailError(f"gmail {op} failed ({type(exc).__name__})") from None
        if response.is_success:
            return response
        status = response.status_code
        if allow_404 and status == 404:
            return None
        message = f"gmail {op} rejected (status {status})"
        reconnect = False
        if status == 403 and (reason := _403_reason(response)):
            message += f": {reason}"
        elif status in (401, 403):
            # A connection made without the Gmail permission, access revoked
            # in the Google account, or a password change (spec §2).
            message += f"; {GMAIL_RECONNECT_HINT}"
            reconnect = True
        elif status == 429 or status >= 500:
            message += "; it will retry next run"
        raise GmailError(message, status=status, reconnect=reconnect)

    def _json(self, response: httpx.Response, op: str) -> dict:
        try:
            data = response.json()
        except ValueError:
            raise GmailError(f"gmail {op} returned no json") from None
        if not isinstance(data, dict):
            raise GmailError(f"gmail {op} returned no json")
        return data

    def get_profile(self) -> str:
        """The inbox's address, lower-cased (allowed by gmail.readonly)."""
        data = self._json(self._get("profile", GMAIL_PROFILE_API, {"fields": "emailAddress"}), "profile")
        address = normalize_address(data.get("emailAddress"))
        if address is None:
            raise GmailError("gmail profile returned no usable address")
        return address

    def list_message_ids(self, query: str, max_ids: int) -> tuple[list[str], bool]:
        """Ids of the messages matching `query`, as Gmail orders them (newest
        first), up to `max_ids`. Also returns whether more were left."""
        ids: list[str] = []
        params: dict = {"q": query, "maxResults": min(_PAGE_SIZE, max_ids), "fields": "messages(id),nextPageToken"}
        while True:
            data = self._json(self._get("list", GMAIL_API, params), "list")
            messages = data.get("messages", [])
            if not isinstance(messages, list):
                raise GmailError("gmail list returned no message list")
            for item in messages:
                if isinstance(item, dict) and is_gmail_id(item.get("id")):
                    ids.append(item["id"])
            token = data.get("nextPageToken")
            has_more = isinstance(token, str) and bool(token)
            if len(ids) >= max_ids:
                return ids[:max_ids], has_more or len(ids) > max_ids
            if not has_more:
                return ids, False
            params = {**params, "pageToken": token, "maxResults": min(_PAGE_SIZE, max_ids - len(ids))}

    def get_metadata(self, message_id: str) -> GmailMessage | None:
        """One message's metadata, or None when it is gone (deleted since it
        was listed)."""
        if not is_gmail_id(message_id):
            raise GmailError("gmail get refused an invalid message id")
        params = [
            ("format", "metadata"),
            *(("metadataHeaders", name) for name in METADATA_HEADERS),
            ("fields", "id,threadId,internalDate,labelIds,snippet,payload/headers"),
        ]
        response = self._get("get", f"{GMAIL_API}/{quote(message_id, safe='')}", params, allow_404=True)
        if response is None:
            return None
        data = self._json(response, "get")
        thread_id = data.get("threadId")
        try:
            internal_date = int(data.get("internalDate"))
        except (TypeError, ValueError):
            raise GmailError("gmail get returned no usable date") from None
        if data.get("id") != message_id or not is_gmail_id(thread_id):
            raise GmailError("gmail get returned no usable id")
        headers: dict[str, str] = {}
        payload = data.get("payload")
        raw_headers = payload.get("headers", []) if isinstance(payload, dict) else []
        for header in raw_headers if isinstance(raw_headers, list) else []:
            if not isinstance(header, dict):
                continue
            name, value = header.get("name"), header.get("value")
            if isinstance(name, str) and isinstance(value, str):
                # First occurrence wins, as mail clients show it.
                headers.setdefault(name.casefold(), value)
        labels = data.get("labelIds")
        snippet = data.get("snippet")
        return GmailMessage(
            id=message_id,
            thread_id=thread_id,
            internal_date=internal_date,
            label_ids=tuple(x for x in labels if isinstance(x, str)) if isinstance(labels, list) else (),
            headers=headers,
            snippet=snippet if isinstance(snippet, str) else "",
        )
