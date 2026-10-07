import httpx
import pytest
from cryptography.fernet import InvalidToken

from app.services import google_docs_service
from app.services.google_docs_service import store_token

DOC_ID = "1AbC_dEf-2GhIjKlMnOp"
FAIL = {"detail": "couldn't load doc"}


@pytest.fixture()
def connected_token(db_session):
    store_token(db_session, {"refresh_token": "rt"}, scopes="s")


def fake_post(status=200, payload=None):
    payload = {"access_token": "at"} if payload is None else payload

    def _post(url, data=None, **kw):
        return httpx.Response(status, json=payload, request=httpx.Request("POST", url))

    return _post


def fake_get(status=200, text=""):
    def _get(url, **kw):
        return httpx.Response(status, text=text, request=httpx.Request("GET", url))

    return _get


def _call(client, ref=DOC_ID):
    return client.get("/api/docs/content", params={"doc_ref": ref})


def test_content_requires_auth(client):
    assert _call(client).status_code == 401


def test_content_returns_text(logged_in_client, connected_token, monkeypatch):
    monkeypatch.setattr(httpx, "post", fake_post())
    monkeypatch.setattr(httpx, "get", fake_get(200, "essay prompt"))
    response = _call(logged_in_client, f"https://docs.google.com/document/d/{DOC_ID}/edit")
    assert response.status_code == 200
    assert response.json() == {"content": "essay prompt"}


@pytest.mark.parametrize("status", [403, 404])
def test_content_502_on_export_failure(logged_in_client, connected_token, monkeypatch, status):
    monkeypatch.setattr(httpx, "post", fake_post())
    monkeypatch.setattr(httpx, "get", fake_get(status))
    response = _call(logged_in_client)
    assert response.status_code == 502
    assert response.json() == FAIL


def test_content_502_on_network_error(logged_in_client, connected_token, monkeypatch):
    monkeypatch.setattr(httpx, "post", fake_post())

    def _get(url, **kw):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "get", _get)
    response = _call(logged_in_client)
    assert response.status_code == 502
    assert response.json() == FAIL


def test_content_502_when_not_connected(logged_in_client):
    response = _call(logged_in_client)
    assert response.status_code == 502
    assert response.json() == FAIL


def test_content_502_when_refresh_rejected(logged_in_client, connected_token, monkeypatch):
    monkeypatch.setattr(httpx, "post", fake_post(400, {"error": "invalid_grant"}))
    response = _call(logged_in_client)
    assert response.status_code == 502
    assert response.json() == FAIL


def test_content_502_when_decrypt_fails(logged_in_client, connected_token, monkeypatch):
    def bad(_):
        raise InvalidToken()

    monkeypatch.setattr(google_docs_service, "decrypt_value", bad)
    response = _call(logged_in_client)
    assert response.status_code == 502
    assert response.json() == FAIL


@pytest.mark.parametrize("ref", ["../../etc", "abc/def", "", "https://evil.com/document/d/x"])
def test_content_422_on_invalid_ref(logged_in_client, ref):
    response = _call(logged_in_client, ref)
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid doc reference"}


# -- every 502 path logs a scrubbed warning -----------------------------------


def _warnings(caplog):
    return [r for r in caplog.records if r.name == "app.api.docs" and r.levelname == "WARNING"]


def test_content_logs_status_when_export_rejected(logged_in_client, connected_token, monkeypatch, caplog):
    monkeypatch.setattr(httpx, "post", fake_post())
    monkeypatch.setattr(httpx, "get", fake_get(403, "secret-body-from-google"))
    with caplog.at_level("WARNING", logger="app.api.docs"):
        assert _call(logged_in_client).status_code == 502
    messages = [r.getMessage() for r in _warnings(caplog)]
    assert len(messages) == 1
    assert "403" in messages[0]
    assert "secret-body-from-google" not in messages[0]


def test_content_logs_when_not_connected(logged_in_client, caplog):
    with caplog.at_level("WARNING", logger="app.api.docs"):
        assert _call(logged_in_client).status_code == 502
    assert "not connected" in " ".join(r.getMessage() for r in _warnings(caplog))


def test_content_logs_when_refresh_rejected_without_leaking_tokens(
    logged_in_client, connected_token, monkeypatch, caplog
):
    monkeypatch.setattr(httpx, "post", fake_post(400, {"error": "invalid_grant"}))
    with caplog.at_level("WARNING", logger="app.api.docs"):
        assert _call(logged_in_client).status_code == 502
    text = " ".join(r.getMessage() for r in _warnings(caplog))
    assert "400" in text
    assert "invalid_grant" not in text
    assert "rt" not in text.split()


def test_content_logs_network_error_type(logged_in_client, connected_token, monkeypatch, caplog):
    monkeypatch.setattr(httpx, "post", fake_post())

    def _get(url, **kw):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "get", _get)
    with caplog.at_level("WARNING", logger="app.api.docs"):
        assert _call(logged_in_client).status_code == 502
    assert "ReadTimeout" in " ".join(r.getMessage() for r in _warnings(caplog))
