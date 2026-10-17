"""GoogleGmailClient against httpx.MockTransport: never the network."""

import json

import httpx
import pytest

from app.services.gmail.client import (
    GMAIL_API,
    GMAIL_RECONNECT_HINT,
    GmailError,
    GmailMessage,
    GoogleGmailClient,
)

TOKEN = "ya29.secret-access-token"


class FakeGmail:
    """Scripted Gmail API: `pages` for messages.list (by page token) and
    `messages` for messages.get; records every request."""

    def __init__(self, pages=None, messages=None, status=None, body=None, profile=None):
        self.profile = profile if profile is not None else {"emailAddress": "Me@Gmail.com", "messagesTotal": 3}
        self.pages = pages or {}
        self.messages = messages or {}
        self.status = status
        self.body = body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status is not None:
            return httpx.Response(self.status, json=self.body or {"error": {"message": "secret body text"}})
        path = request.url.path
        if path.endswith("/users/me/profile"):
            return httpx.Response(200, json=self.profile)
        if path.endswith("/users/me/messages"):
            token = request.url.params.get("pageToken", "")
            return httpx.Response(200, json=self.pages.get(token, {}))
        message_id = path.rsplit("/", 1)[1]
        if message_id not in self.messages:
            return httpx.Response(404, json={"error": {"code": 404}})
        return httpx.Response(200, json=self.messages[message_id])

    def client(self) -> GoogleGmailClient:
        return GoogleGmailClient(TOKEN, transport=httpx.MockTransport(self))


def _message(mid="18c2f0a1b2c3d4e5", **extra):
    data = {
        "id": mid,
        "threadId": "18c2f0a1b2c3d400",
        "internalDate": "1759320000000",
        "labelIds": ["INBOX", "CATEGORY_PERSONAL"],
        "snippet": "We&#39;d like to invite you to interview",
        "payload": {
            "headers": [
                {"name": "From", "value": "Stripe Recruiting <recruiting@stripe.com>"},
                {"name": "To", "value": "me@gmail.com"},
                {"name": "Subject", "value": "Interview invitation"},
                {"name": "Date", "value": "Wed, 1 Oct 2025 12:00:00 +0000"},
            ]
        },
    }
    data.update(extra)
    return data


def test_list_pages_until_the_end_and_sends_the_token():
    fake = FakeGmail(
        pages={
            "": {"messages": [{"id": "a1"}, {"id": "a2"}], "nextPageToken": "p2"},
            "p2": {"messages": [{"id": "a3"}]},
        }
    )
    client = fake.client()
    ids, more = client.list_message_ids("in:inbox newer_than:30d", 5000)
    client.close()

    assert (ids, more) == (["a1", "a2", "a3"], False)
    assert [r.url.params.get("pageToken") for r in fake.requests] == [None, "p2"]
    first = fake.requests[0]
    assert str(first.url).startswith(GMAIL_API)
    assert first.url.params["q"] == "in:inbox newer_than:30d"
    assert first.url.params["maxResults"] == "500"
    assert all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in fake.requests)


def test_list_stops_at_max_ids_and_says_more_were_left():
    fake = FakeGmail(
        pages={
            "": {"messages": [{"id": "a1"}, {"id": "a2"}], "nextPageToken": "p2"},
            "p2": {"messages": [{"id": "a3"}, {"id": "a4"}], "nextPageToken": "p3"},
        }
    )
    ids, more = fake.client().list_message_ids("q", 3)
    assert (ids, more) == (["a1", "a2", "a3"], True)
    assert [r.url.params["maxResults"] for r in fake.requests] == ["3", "1"]


def test_list_with_no_messages_and_invalid_ids_dropped():
    fake = FakeGmail(pages={"": {"messages": [{"id": "ok1"}, {"id": "../etc"}, {"id": 5}, "x"]}})
    assert fake.client().list_message_ids("q", 10) == (["ok1"], False)
    assert FakeGmail(pages={"": {"resultSizeEstimate": 0}}).client().list_message_ids("q", 10) == ([], False)


def test_get_metadata_parses_headers_and_requests_metadata_only():
    fake = FakeGmail(messages={"18c2f0a1b2c3d4e5": _message()})
    message = fake.client().get_metadata("18c2f0a1b2c3d4e5")

    assert message == GmailMessage(
        id="18c2f0a1b2c3d4e5",
        thread_id="18c2f0a1b2c3d400",
        internal_date=1759320000000,
        label_ids=("INBOX", "CATEGORY_PERSONAL"),
        headers={
            "from": "Stripe Recruiting <recruiting@stripe.com>",
            "to": "me@gmail.com",
            "subject": "Interview invitation",
            "date": "Wed, 1 Oct 2025 12:00:00 +0000",
        },
        snippet="We&#39;d like to invite you to interview",
    )
    (request,) = fake.requests
    params = request.url.params
    assert params["format"] == "metadata"
    assert params.get_list("metadataHeaders") == ["From", "To", "Cc", "Subject", "Date"]
    assert "payload/headers" in params["fields"] and "parts" not in params["fields"]
    assert "body" not in str(request.url) and "raw" not in str(request.url) and "full" not in str(request.url)


def test_get_metadata_of_a_deleted_message_is_none():
    assert FakeGmail().client().get_metadata("abc123") is None


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a" * 101, "id?format=full"])
def test_get_refuses_an_invalid_id_before_any_request(bad):
    fake = FakeGmail()
    with pytest.raises(GmailError):
        fake.client().get_metadata(bad)
    assert fake.requests == []


@pytest.mark.parametrize(
    "data",
    [
        _message(threadId="../x"),
        _message(id="other"),
        _message(internalDate="soon"),
        _message(internalDate=None),
    ],
)
def test_get_refuses_unusable_responses(data):
    fake = FakeGmail(messages={"18c2f0a1b2c3d4e5": data})
    with pytest.raises(GmailError):
        fake.client().get_metadata("18c2f0a1b2c3d4e5")


def test_odd_header_shapes_are_tolerated_and_the_first_header_wins():
    data = _message(
        labelIds="INBOX",
        snippet=None,
        payload={"headers": [{"name": "Subject", "value": "One"}, {"name": "subject", "value": "Two"}, "junk", {"name": 1}]},
    )
    message = FakeGmail(messages={"abc": {**data, "id": "abc"}}).client().get_metadata("abc")
    assert message.headers == {"subject": "One"}
    assert message.label_ids == () and message.snippet == ""


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_say_reconnect_and_leak_nothing(status):
    fake = FakeGmail(status=status)
    with pytest.raises(GmailError) as info:
        fake.client().list_message_ids("q", 10)
    message = str(info.value)
    assert message == f"gmail list rejected (status {status}); {GMAIL_RECONNECT_HINT}"
    assert info.value.reconnect and info.value.status == status
    assert TOKEN not in message and "secret body" not in message


def test_a_403_rate_limit_is_not_a_reconnect():
    body = {"error": {"errors": [{"reason": "userRateLimitExceeded", "message": "secret body"}]}}
    with pytest.raises(GmailError) as info:
        FakeGmail(status=403, body=body).client().get_metadata("abc")
    assert str(info.value) == "gmail get rejected (status 403): Gmail rate limit hit; it will retry next run"
    assert not info.value.reconnect


@pytest.mark.parametrize("status", [429, 500, 503])
def test_rate_limits_and_server_errors_retry_next_run(status):
    with pytest.raises(GmailError) as info:
        FakeGmail(status=status).client().list_message_ids("q", 10)
    assert str(info.value) == f"gmail list rejected (status {status}); it will retry next run"
    assert not info.value.reconnect


def test_network_errors_name_only_the_exception_type():
    def boom(request):
        raise httpx.ConnectError(f"cannot reach {request.url} with {TOKEN}")

    client = GoogleGmailClient(TOKEN, transport=httpx.MockTransport(boom))
    with pytest.raises(GmailError) as info:
        client.list_message_ids("q", 10)
    assert str(info.value) == "gmail list failed (ConnectError)" and info.value.status is None


def test_non_json_responses_are_errors():
    client = GoogleGmailClient(TOKEN, transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    with pytest.raises(GmailError, match="no json"):
        client.list_message_ids("q", 10)
    client = GoogleGmailClient(TOKEN, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=json.dumps([1]))))
    with pytest.raises(GmailError, match="no json"):
        client.get_metadata("abc")


def test_get_profile_reads_the_inbox_address_lower_cased():
    fake = FakeGmail()
    client = fake.client()
    assert client.get_profile() == "me@gmail.com"
    client.close()
    (request,) = fake.requests
    assert request.method == "GET"
    assert str(request.url).startswith("https://gmail.googleapis.com/gmail/v1/users/me/profile")
    assert request.url.params.get("fields") == "emailAddress"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    "profile",
    [{}, {"emailAddress": None}, {"emailAddress": 42}, {"emailAddress": "no-at-sign"}, {"emailAddress": "a b@c.com"},
     {"emailAddress": "<x@y.com>"}, {"emailAddress": "x@" + "y" * 400}, {"emailAddress": "x@y.com/../z"}],
)
def test_get_profile_refuses_an_unusable_address(profile):
    with pytest.raises(GmailError) as exc:
        FakeGmail(profile=profile).client().get_profile()
    assert str(exc.value) == "gmail profile returned no usable address"


def test_get_profile_failure_says_reconnect_and_leaks_nothing():
    with pytest.raises(GmailError) as exc:
        FakeGmail(status=401).client().get_profile()
    assert exc.value.reconnect and exc.value.status == 401
    assert str(exc.value) == f"gmail profile rejected (status 401); {GMAIL_RECONNECT_HINT}"
    assert TOKEN not in str(exc.value) and "secret body" not in str(exc.value)
