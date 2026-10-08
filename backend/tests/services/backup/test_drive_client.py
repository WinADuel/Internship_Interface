"""GoogleDriveClient against httpx.MockTransport: no request leaves the process."""

import json

import httpx
import pytest

from app.services.backup import drive_client
from app.services.backup.drive_client import (
    DRIVE_API,
    DRIVE_UPLOAD_API,
    FOLDER_MIME,
    FOLDER_NAME,
    DriveError,
    DriveFile,
    GoogleDriveClient,
)
from app.services.sheets_client import RECONNECT_HINT

TOKEN = "ya29.secret-access-token"
SESSION_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=sess-123"


class FakeDrive:
    """A tiny in-memory Drive behind a MockTransport, recording each request."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []
        self.folders: list[str] = []
        self.files: list[DriveFile] = []  # newest first
        self.pages: list[dict] | None = None  # scripted list responses
        self.fail: httpx.Response | Exception | None = None
        self.next_id = 0

    def _id(self, prefix):
        self.next_id += 1
        return f"{prefix}{self.next_id}"

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.bodies.append(request.read())
        if isinstance(self.fail, Exception):
            raise self.fail
        if self.fail is not None:
            return self.fail
        url, method = str(request.url).split("?")[0], request.method
        params = request.url.params
        if method == "GET" and url == DRIVE_API:
            if "mimeType" in params["q"]:
                return httpx.Response(200, json={"files": [{"id": f} for f in self.folders[:1]]})
            if self.pages is not None:
                return httpx.Response(200, json=self.pages[len([r for r in self.requests if r.method == "GET"]) - 1])
            return httpx.Response(200, json={"files": [{"id": f.id, "name": f.name} for f in self.files]})
        if method == "POST" and url == DRIVE_API:
            folder = self._id("folder")
            self.folders.append(folder)
            return httpx.Response(200, json={"id": folder})
        if method == "POST" and url == DRIVE_UPLOAD_API and params["uploadType"] == "multipart":
            return httpx.Response(200, json={"id": self._id("file")})
        if method == "POST" and url == DRIVE_UPLOAD_API and params["uploadType"] == "resumable":
            return httpx.Response(200, headers={"Location": SESSION_URL})
        if method == "PUT" and str(request.url) == SESSION_URL:
            return httpx.Response(200, json={"id": self._id("file")})
        if method == "DELETE" and url.startswith(DRIVE_API + "/"):
            return httpx.Response(204)
        return httpx.Response(418)


@pytest.fixture()
def drive():
    return FakeDrive()


@pytest.fixture()
def client(drive):
    return GoogleDriveClient(TOKEN, transport=drive.transport())


def test_every_request_carries_the_bearer_token(drive, client):
    client.find_or_create_folder()
    assert drive.requests and all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in drive.requests)


def test_creates_the_folder_when_missing(drive, client):
    assert client.find_or_create_folder() == "folder1"
    lookup, create = drive.requests
    assert lookup.method == "GET"
    assert lookup.url.params["q"] == (
        f"name = '{FOLDER_NAME}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    )
    assert create.method == "POST" and str(create.url).startswith(DRIVE_API)
    assert json.loads(drive.bodies[1]) == {"name": FOLDER_NAME, "mimeType": FOLDER_MIME}


def test_reuses_an_existing_folder(drive, client):
    drive.folders = ["existing-folder"]
    assert client.find_or_create_folder() == "existing-folder"
    assert [r.method for r in drive.requests] == ["GET"]


def test_folder_name_is_quoted_in_the_query(drive, client):
    client.find_or_create_folder("Bob's \\ backups")
    assert drive.requests[0].url.params["q"].startswith("name = 'Bob\\'s \\\\ backups' and")


def test_small_upload_is_one_multipart_request(drive, client, tmp_path):
    path = tmp_path / "x.enc"
    path.write_bytes(b"ciphertext-bytes")
    assert client.upload("folder9", "tracker-20261008T023000Z.dump.enc", path) == "file1"
    (request,) = drive.requests
    assert request.method == "POST" and str(request.url).startswith(DRIVE_UPLOAD_API)
    assert request.url.params["uploadType"] == "multipart"
    content_type = request.headers["content-type"]
    assert content_type.startswith("multipart/related; boundary=")
    boundary = content_type.split("boundary=")[1]
    parts = drive.bodies[0].split(f"--{boundary}".encode())
    assert parts[0] == b"" and parts[-1] == b"--\r\n"
    meta_part, file_part = parts[1], parts[2]
    assert b"Content-Type: application/json; charset=UTF-8" in meta_part
    metadata = json.loads(meta_part.split(b"\r\n\r\n", 1)[1])
    assert metadata == {
        "name": "tracker-20261008T023000Z.dump.enc",
        "parents": ["folder9"],
        "mimeType": "application/octet-stream",
    }
    assert file_part.split(b"\r\n\r\n", 1)[1] == b"ciphertext-bytes\r\n"


def test_large_upload_streams_through_a_resumable_session(drive, client, tmp_path, monkeypatch):
    monkeypatch.setattr(drive_client, "MULTIPART_LIMIT", 10)
    monkeypatch.setattr(drive_client, "_CHUNK", 7)
    data = bytes(range(256)) * 3
    path = tmp_path / "x.enc"
    path.write_bytes(data)
    assert client.upload("folder9", "tracker-20261008T023000Z.dump.enc", path) == "file1"
    start, put = drive.requests
    assert start.url.params["uploadType"] == "resumable"
    assert start.headers["x-upload-content-length"] == str(len(data))
    assert json.loads(drive.bodies[0])["parents"] == ["folder9"]
    assert put.method == "PUT" and str(put.url) == SESSION_URL
    assert put.headers["content-length"] == str(len(data))
    assert "transfer-encoding" not in put.headers
    assert drive.bodies[1] == data


@pytest.mark.parametrize("location", ["", "http://www.googleapis.com/upload", "https://evil.example/upload"])
def test_resumable_session_must_point_at_google(drive, client, tmp_path, monkeypatch, location):
    monkeypatch.setattr(drive_client, "MULTIPART_LIMIT", 1)
    path = tmp_path / "x.enc"
    path.write_bytes(b"abc")
    drive.fail = httpx.Response(200, headers={"Location": location} if location else {})
    with pytest.raises(DriveError, match="no usable session"):
        client.upload("folder9", "a.dump.enc", path)
    assert len(drive.requests) == 1


def test_list_files_pages_newest_first(drive, client):
    drive.pages = [
        {"files": [{"id": "a", "name": "tracker-20261008T023000Z.dump.enc"}], "nextPageToken": "p2"},
        {"files": [{"id": "b", "name": "notes.txt"}, {"id": "c"}]},
    ]
    assert client.list_files("folder9") == [
        DriveFile("a", "tracker-20261008T023000Z.dump.enc"),
        DriveFile("b", "notes.txt"),
    ]
    first, second = drive.requests
    assert first.url.params["q"] == "'folder9' in parents and trashed = false"
    assert first.url.params["orderBy"] == "createdTime desc"
    assert "pageToken" not in first.url.params
    assert second.url.params["pageToken"] == "p2"


def test_list_stops_after_a_bounded_number_of_pages(drive, client):
    drive.pages = [{"files": [], "nextPageToken": "again"}] * 50
    client.list_files("folder9")
    assert len(drive.requests) == drive_client._MAX_LIST_PAGES


def test_delete_and_already_deleted(drive, client):
    client.delete("file-1")
    assert drive.requests[0].method == "DELETE"
    assert str(drive.requests[0].url) == f"{DRIVE_API}/file-1"
    drive.fail = httpx.Response(404, text="not found")
    client.delete("file-2")  # gone already: fine


@pytest.mark.parametrize("bad_id", ["", "../x", "a b", "x'y", "a" * 201])
def test_bad_ids_never_reach_a_url_or_query(drive, client, bad_id, tmp_path):
    with pytest.raises(DriveError):
        client.delete(bad_id)
    with pytest.raises(DriveError):
        client.list_files(bad_id)
    with pytest.raises(DriveError):
        client.upload(bad_id, "a.enc", tmp_path / "missing")
    assert drive.requests == []


def test_an_odd_id_from_drive_is_refused(drive, client):
    drive.fail = httpx.Response(200, json={"files": [{"id": "../../etc"}]})
    with pytest.raises(DriveError, match="no usable id"):
        client.find_or_create_folder()


@pytest.mark.parametrize("status", [401, 403])
def test_auth_rejections_suggest_reconnecting(drive, client, status):
    drive.fail = httpx.Response(status, text=f"secret body {TOKEN}")
    with pytest.raises(DriveError) as excinfo:
        client.find_or_create_folder()
    message = str(excinfo.value)
    assert message == f"drive folder lookup rejected (status {status}); {RECONNECT_HINT}"


def test_a_full_drive_is_named_without_echoing_the_body(drive, client):
    body = {"error": {"errors": [{"reason": "storageQuotaExceeded", "message": "secret body"}]}}
    drive.fail = httpx.Response(403, json=body)
    with pytest.raises(DriveError) as excinfo:
        client.find_or_create_folder()
    assert str(excinfo.value) == "drive folder lookup rejected (status 403): Google Drive is full"


@pytest.mark.parametrize("status", [404, 500, 503])
def test_other_statuses_give_a_short_error(drive, client, status):
    drive.fail = httpx.Response(status, text=f"secret body {TOKEN}")
    with pytest.raises(DriveError) as excinfo:
        client.find_or_create_folder()
    assert str(excinfo.value) == f"drive folder lookup rejected (status {status})"


@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout(f"timed out {TOKEN}"), httpx.ConnectError(f"refused {TOKEN}")]
)
def test_network_errors_give_the_type_only(drive, client, exc):
    drive.fail = exc
    with pytest.raises(DriveError) as excinfo:
        client.find_or_create_folder()
    assert str(excinfo.value) == f"drive folder lookup failed ({type(exc).__name__})"


@pytest.mark.parametrize("response", [httpx.Response(200, text="not json"), httpx.Response(200, json=["x"])])
def test_non_json_success_is_an_error(drive, client, response):
    drive.fail = response
    with pytest.raises(DriveError, match="returned no json"):
        client.find_or_create_folder()
