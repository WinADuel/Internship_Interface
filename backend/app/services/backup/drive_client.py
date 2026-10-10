"""A minimal Google Drive v3 client for the off-site backup copy (Phase 3
spec §4.4). Behind a Protocol so tests use a fake; the real client takes an
httpx transport so its own tests run against httpx.MockTransport.

It only ever sees what the `drive.file` permission allows: files and folders
this app created. That is the backup folder and the copies in it, so no new
Google permission is needed and nothing else in the owner's Drive is reachable.

Uploads under MULTIPART_LIMIT (Google's limit for `uploadType=multipart`)
go up in one request; bigger ones use a resumable session, streamed from
disk in a single PUT. Errors never include tokens, upload session URLs or
response bodies."""

import json
import re
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlsplit

import httpx

from app.services.sheets_client import RECONNECT_HINT

DRIVE_API = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_NAME = "Internship Tracker Backups"
FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_MIME = "application/octet-stream"
MULTIPART_LIMIT = 5 * 1024 * 1024
_TIMEOUT = httpx.Timeout(30.0)
_CHUNK = 1024 * 1024
_MAX_LIST_PAGES = 20  # 100 per page: far more copies than are ever kept
# Drive ids are url-safe base64-ish; anything else is refused before it can
# reach a query string or a URL path.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
# 403 reasons that a reconnect would not fix. Only these fixed strings are
# ever shown; nothing from the response body is echoed.
_403_REASONS = {
    "storageQuotaExceeded": "Google Drive is full",
    "quotaExceeded": "Google Drive is full",
    "rateLimitExceeded": "Google rate limit hit; it will retry tomorrow",
    "userRateLimitExceeded": "Google rate limit hit; it will retry tomorrow",
}


class DriveError(Exception):
    """A Google Drive call failed (non-2xx response or network error)."""


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str


class DriveClient(Protocol):
    def find_or_create_folder(self, name: str) -> str: ...

    def upload(self, folder_id: str, name: str, path: Path) -> str: ...

    def list_files(self, folder_id: str) -> list[DriveFile]: ...

    def delete(self, file_id: str) -> None: ...


def _check_id(value, op: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise DriveError(f"drive {op} returned no usable id")
    return value


def _query_literal(value: str) -> str:
    """A string literal for a Drive `q` query."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


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


class GoogleDriveClient:
    def __init__(self, access_token: str, transport: httpx.BaseTransport | None = None):
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._transport = transport

    def _request(self, op: str, method: str, url: str, *, allow_404: bool = False, **kwargs) -> httpx.Response:
        headers = {**self._headers, **kwargs.pop("headers", {})}
        try:
            with httpx.Client(transport=self._transport, timeout=_TIMEOUT) as client:
                response = client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise DriveError(f"drive {op} failed ({type(exc).__name__})") from None
        if response.is_success or (allow_404 and response.status_code == 404):
            return response
        message = f"drive {op} rejected (status {response.status_code})"
        if response.status_code == 403 and (reason := _403_reason(response)):
            message += f": {reason}"
        elif response.status_code in (401, 403):
            # Typically a Google connection made before drive.file was requested,
            # or access revoked in the Google account.
            message += f"; {RECONNECT_HINT}"
        raise DriveError(message)

    def _json(self, response: httpx.Response, op: str) -> dict:
        try:
            data = response.json()
        except ValueError:
            raise DriveError(f"drive {op} returned no json") from None
        if not isinstance(data, dict):
            raise DriveError(f"drive {op} returned no json")
        return data

    def find_or_create_folder(self, name: str = FOLDER_NAME) -> str:
        """The id of the app's folder called `name`, created if missing. Only
        app-created folders are visible (drive.file), so a folder of the same
        name the owner made by hand is never written into."""
        query = (
            f"name = {_query_literal(name)} and mimeType = {_query_literal(FOLDER_MIME)} and trashed = false"
        )
        response = self._request(
            "folder lookup",
            "GET",
            DRIVE_API,
            params={"q": query, "fields": "files(id)", "orderBy": "createdTime", "pageSize": 1, "spaces": "drive"},
        )
        files = self._json(response, "folder lookup").get("files")
        if isinstance(files, list) and files and isinstance(files[0], dict):
            return _check_id(files[0].get("id"), "folder lookup")
        response = self._request(
            "folder create",
            "POST",
            DRIVE_API,
            params={"fields": "id"},
            json={"name": name, "mimeType": FOLDER_MIME},
        )
        return _check_id(self._json(response, "folder create").get("id"), "folder create")

    def upload(self, folder_id: str, name: str, path: Path) -> str:
        """Upload the file at `path` into the folder as `name`; returns its id."""
        _check_id(folder_id, "upload")
        metadata = {"name": name, "parents": [folder_id], "mimeType": FILE_MIME}
        size = Path(path).stat().st_size
        if size <= MULTIPART_LIMIT:
            response = self._upload_multipart(metadata, Path(path).read_bytes())
        else:
            response = self._upload_resumable(metadata, Path(path), size)
        return _check_id(self._json(response, "upload").get("id"), "upload")

    def _upload_multipart(self, metadata: dict, data: bytes) -> httpx.Response:
        boundary = f"tracker-{secrets.token_hex(16)}"
        body = b"".join(
            [
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
                json.dumps(metadata).encode(),
                f"\r\n--{boundary}\r\nContent-Type: {FILE_MIME}\r\n\r\n".encode(),
                data,
                f"\r\n--{boundary}--\r\n".encode(),
            ]
        )
        return self._request(
            "upload",
            "POST",
            DRIVE_UPLOAD_API,
            params={"uploadType": "multipart", "fields": "id"},
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            content=body,
        )

    def _upload_resumable(self, metadata: dict, path: Path, size: int) -> httpx.Response:
        start = self._request(
            "upload start",
            "POST",
            DRIVE_UPLOAD_API,
            params={"uploadType": "resumable", "fields": "id"},
            headers={"X-Upload-Content-Type": FILE_MIME, "X-Upload-Content-Length": str(size)},
            json=metadata,
        )
        session_url = start.headers.get("location", "")
        parts = urlsplit(session_url)
        # The session URL carries the upload's authority: it must be Google's.
        if parts.scheme != "https" or parts.hostname != "www.googleapis.com":
            raise DriveError("drive upload start returned no usable session")

        def chunks() -> Iterator[bytes]:
            with open(path, "rb") as source:
                while block := source.read(_CHUNK):
                    yield block

        return self._request(
            "upload",
            "PUT",
            session_url,
            headers={"Content-Type": FILE_MIME, "Content-Length": str(size)},
            content=chunks(),
        )

    def list_files(self, folder_id: str) -> list[DriveFile]:
        """The files in the folder, newest first (by Drive's createdTime)."""
        _check_id(folder_id, "list")
        params = {
            "q": f"{_query_literal(folder_id)} in parents and trashed = false",
            "fields": "nextPageToken,files(id,name)",
            "orderBy": "createdTime desc",
            "pageSize": 100,
            "spaces": "drive",
        }
        found: list[DriveFile] = []
        for _ in range(_MAX_LIST_PAGES):
            data = self._json(self._request("list", "GET", DRIVE_API, params=params), "list")
            files = data.get("files")
            if not isinstance(files, list):
                raise DriveError("drive list returned no file list")
            for item in files:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    found.append(DriveFile(_check_id(item.get("id"), "list"), item["name"]))
            token = data.get("nextPageToken")
            if not isinstance(token, str) or not token:
                break
            params["pageToken"] = token
        return found

    def delete(self, file_id: str) -> None:
        """Delete a file for good; one that is already gone counts as deleted."""
        _check_id(file_id, "delete")
        self._request("delete", "DELETE", f"{DRIVE_API}/{quote(file_id, safe='')}", allow_404=True)
