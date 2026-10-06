import httpx
import pytest
from cryptography.fernet import InvalidToken

from app.services import google_docs_service
from app.services.errors import (
    GoogleAuthError,
    GoogleDocsFetchError,
    GoogleNotConnectedError,
    InvalidDocRefError,
)
from app.services.google_docs_service import (
    extract_doc_id,
    fetch_doc_text,
    get_valid_access_token,
    store_token,
)

DOC_ID = "1AbC_dEf-2GhIjKlMnOp"


@pytest.fixture()
def connected_token(db_session):
    store_token(db_session, {"refresh_token": "rt"}, scopes="s")


def _patch_refresh(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, data=None, **kw: httpx.Response(
            200, json={"access_token": "at"}, request=httpx.Request("POST", url)
        ),
    )


def fake_get_returning_status(status, text="", calls=None):
    def _get(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        return httpx.Response(status, text=text, request=httpx.Request("GET", url))

    return _get


@pytest.mark.parametrize(
    "doc_ref",
    [
        DOC_ID,
        f"https://docs.google.com/document/d/{DOC_ID}/edit",
        f"https://docs.google.com/document/d/{DOC_ID}",
        f"  {DOC_ID}  ",
    ],
)
def test_extract_doc_id_normalizes_forms(doc_ref):
    assert extract_doc_id(doc_ref) == DOC_ID


@pytest.mark.parametrize(
    "doc_ref",
    [
        "../../etc",
        "abc/def",
        "",
        "https://evil.com/document/d/" + DOC_ID,
        "short",
        "http://docs.google.com.evil.com/document/d/" + DOC_ID,
        f"{DOC_ID}?x=1",
    ],
)
def test_extract_doc_id_rejects_invalid(doc_ref):
    with pytest.raises(InvalidDocRefError):
        extract_doc_id(doc_ref)


def test_fetch_doc_text_raises_when_not_connected(db_session):
    with pytest.raises(GoogleNotConnectedError):
        fetch_doc_text(db_session, DOC_ID)


def test_fetch_doc_text_invalid_ref_makes_no_network_call(db_session, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(InvalidDocRefError):
        fetch_doc_text(db_session, "../../etc")


def test_fetch_doc_text_returns_text_and_calls_export(db_session, connected_token, monkeypatch):
    _patch_refresh(monkeypatch)
    calls = []
    monkeypatch.setattr(httpx, "get", fake_get_returning_status(200, "hello doc", calls))
    assert fetch_doc_text(db_session, DOC_ID) == "hello doc"
    url, kwargs = calls[0]
    assert url == f"https://www.googleapis.com/drive/v3/files/{DOC_ID}/export"
    assert kwargs["params"] == {"mimeType": "text/plain"}
    assert kwargs["headers"] == {"Authorization": "Bearer at"}
    assert kwargs["timeout"] == 15.0


@pytest.mark.parametrize("status", [403, 404, 500])
def test_fetch_doc_text_raises_on_api_failure(db_session, connected_token, monkeypatch, status):
    _patch_refresh(monkeypatch)
    monkeypatch.setattr(httpx, "get", fake_get_returning_status(status, "secret body"))
    with pytest.raises(GoogleDocsFetchError) as exc:
        fetch_doc_text(db_session, DOC_ID)
    assert "secret body" not in str(exc.value)


def test_fetch_doc_text_raises_on_network_error(db_session, connected_token, monkeypatch):
    _patch_refresh(monkeypatch)

    def _get(url, **kw):
        raise httpx.ConnectError("boom token=at")

    monkeypatch.setattr(httpx, "get", _get)
    with pytest.raises(GoogleDocsFetchError) as exc:
        fetch_doc_text(db_session, DOC_ID)
    assert "token=at" not in str(exc.value)


def test_get_valid_access_token_maps_decrypt_failure(db_session, connected_token, monkeypatch):
    def bad(_):
        raise InvalidToken()

    monkeypatch.setattr(google_docs_service, "decrypt_value", bad)
    with pytest.raises(GoogleAuthError):
        get_valid_access_token(db_session)
