"""HttpxDiscoveryHttp over httpx.MockTransport with a patched resolver: no
test here opens a socket or performs a real DNS lookup."""

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest

from app.services.discovery import http as http_module
from app.services.discovery.http import (
    PAGE_MAX_BYTES,
    USER_AGENT,
    DiscoveryFetchError,
    FetchResult,
    HttpxDiscoveryHttp,
)
from tests.services.discovery.fakes import (
    FakeDiscoveryHttp,
    UnexpectedRequestError,
    json_result,
)

PUBLIC_V4 = "93.184.216.34"
PUBLIC_V4_B = "93.184.216.35"
PUBLIC_V6 = "2606:4700::1111"

DNS = {
    "example.com": [PUBLIC_V4],
    "api.example.com": [PUBLIC_V4],
    "elsewhere.example": [PUBLIC_V4_B],
    "nvidia.wd5.myworkdayjobs.com": [PUBLIC_V4],
    "other.example": [PUBLIC_V4_B],
    "v6.example": [PUBLIC_V6],
    "localhost": ["127.0.0.1", "::1"],
    "internal.test": ["10.0.0.1"],
    "mixed.test": [PUBLIC_V4, "192.168.1.10"],
    "metadata.test": ["169.254.169.254"],
    "2130706433": ["127.0.0.1"],  # decimal form of 127.0.0.1
    "multi.example": [PUBLIC_V4, PUBLIC_V4_B],
    "fec0.example": ["fec0::1"],
}


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """Patch socket.getaddrinfo for every test here; any unscripted name
    fails like NXDOMAIN. Autouse because every call now resolves and checks
    each hop's address, not just `get_page`."""
    lookups: list[str] = []

    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        lookups.append(host)
        if host not in DNS:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        out = []
        for addr in DNS[host]:
            if ":" in addr:
                out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (addr, port or 0, 0, 0)))
            else:
                out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port or 0)))
        return out

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return lookups


class Recorder:
    """A MockTransport handler that records every request it receives."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def make(handler) -> tuple[HttpxDiscoveryHttp, Recorder]:
    rec = Recorder(handler)
    return HttpxDiscoveryHttp(transport=httpx.MockTransport(rec)), rec


def html(
    body: str = "<html><title>Hi</title></html>", status: int = 200, **headers
) -> httpx.Response:
    return httpx.Response(
        status,
        content=body.encode(),
        headers={"content-type": "text/html; charset=utf-8", **headers},
    )


def redirect(location: str, status: int = 302, **headers) -> httpx.Response:
    return httpx.Response(status, headers={"location": location, **headers})


async def chunks(parts: list[bytes]):
    """An async body with no content-length (the client is async)."""
    for part in parts:
        yield part


# --- get_json ----------------------------------------------------------------


def test_get_json_returns_data_and_etag():
    client, rec = make(lambda r: httpx.Response(200, json={"jobs": [1]}, headers={"etag": '"v2"'}))
    result = client.get_json("https://api.example.com/jobs", max_bytes=1000, timeout=10)
    assert result == FetchResult(
        status=200,
        data={"jobs": [1]},
        text=None,
        etag='"v2"',
        final_url="https://api.example.com/jobs",
    )
    sent = rec.requests[0]
    assert sent.headers["user-agent"] == USER_AGENT
    assert "cookie" not in sent.headers
    assert "authorization" not in sent.headers
    assert "if-none-match" not in sent.headers


def test_get_json_sends_etag_and_handles_304():
    client, rec = make(lambda r: httpx.Response(304, headers={"etag": '"v1"'}))
    result = client.get_json(
        "https://api.example.com/l.json", etag='"v1"', max_bytes=1000, timeout=10
    )
    assert rec.requests[0].headers["if-none-match"] == '"v1"'
    assert result.status == 304
    assert result.data is None and result.text is None
    assert result.etag == '"v1"'


def test_get_json_304_without_etag_header_keeps_sent_etag():
    client, _ = make(lambda r: httpx.Response(304))
    result = client.get_json(
        "https://api.example.com/l.json", etag='"v1"', max_bytes=1000, timeout=10
    )
    assert result.etag == '"v1"'


def test_get_json_error_status_raises_without_body_or_query():
    client, _ = make(lambda r: httpx.Response(500, text="SECRET BODY"))
    with pytest.raises(DiscoveryFetchError) as info:
        client.get_json("https://api.example.com/jobs?token=abc", max_bytes=1000, timeout=10)
    message = str(info.value)
    assert info.value.status == 500
    assert "500" in message
    assert "api.example.com/jobs" in message
    assert "SECRET" not in message
    assert "token=abc" not in message
    assert "\n" not in message


def test_get_json_invalid_json_raises():
    client, _ = make(lambda r: httpx.Response(200, content=b"{not json"))
    with pytest.raises(DiscoveryFetchError, match="invalid json"):
        client.get_json("https://api.example.com/jobs", max_bytes=1000, timeout=10)


def test_get_json_too_large_by_content_length():
    client, _ = make(lambda r: httpx.Response(200, content=b"[" + b"1," * 600 + b"1]"))
    with pytest.raises(DiscoveryFetchError, match="too large"):
        client.get_json("https://api.example.com/jobs", max_bytes=1000, timeout=10)


def test_get_json_too_large_when_streamed_without_length():
    def handler(request):
        return httpx.Response(200, content=chunks([b"x" * 400] * 5))  # chunked, no content-length

    client, _ = make(handler)
    with pytest.raises(DiscoveryFetchError, match="too large"):
        client.get_json("https://api.example.com/jobs", max_bytes=1000, timeout=10)


def test_get_json_transport_error_is_one_line_without_query():
    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    client, _ = make(handler)
    with pytest.raises(DiscoveryFetchError) as info:
        client.get_json("https://api.example.com/jobs?secret=1", max_bytes=1000, timeout=10)
    assert "ConnectTimeout" in str(info.value)
    assert "secret" not in str(info.value)
    assert info.value.status is None


def test_get_json_deadline_covers_slow_body():
    async def slow_body():
        for _ in range(100):
            await asyncio.sleep(0.05)
            yield b" "

    client, _ = make(lambda r: httpx.Response(200, content=slow_body()))
    started = time.monotonic()
    with pytest.raises(DiscoveryFetchError, match="timed out"):
        client.get_json("https://api.example.com/jobs", max_bytes=1000, timeout=0.3)
    assert time.monotonic() - started < 1.5


def test_post_json_deadline_covers_slow_response():
    async def handler(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json={})

    client, _ = make(handler)
    started = time.monotonic()
    with pytest.raises(DiscoveryFetchError, match="timed out"):
        client.post_json("https://api.example.com/jobs", {}, max_bytes=1000, timeout=0.3)
    assert time.monotonic() - started < 1.5


def test_error_message_keeps_path_encoded_so_crlf_cannot_reach_logs():
    client, _ = make(lambda r: httpx.Response(500))
    with pytest.raises(DiscoveryFetchError) as info:
        client.get_json(
            "https://api.example.com/a%0D%0AFAKE-LOG-LINE?x=secret", max_bytes=1000, timeout=10
        )
    message = str(info.value)
    assert "\r" not in message and "\n" not in message
    assert "api.example.com/a%0D%0AFAKE-LOG-LINE" in message
    assert "secret" not in message


def test_calling_from_inside_a_running_event_loop_fails_clearly():
    client, rec = make(lambda r: httpx.Response(200, json={}))

    async def inside_loop():
        client.get_json("https://api.example.com/jobs", max_bytes=1000, timeout=10)

    with pytest.raises(RuntimeError, match="event loop"):
        asyncio.run(inside_loop())
    assert rec.requests == []


def test_get_json_follows_redirects_and_drops_cookies():
    def handler(request):
        if request.url.path == "/old":
            return redirect("/new", **{"set-cookie": "sid=1; Path=/"})
        return httpx.Response(200, json=[1])

    client, rec = make(handler)
    result = client.get_json("https://api.example.com/old", max_bytes=1000, timeout=10)
    assert result.data == [1]
    assert result.final_url == "https://api.example.com/new"
    assert "cookie" not in rec.requests[1].headers


def test_get_json_too_many_redirects():
    client, rec = make(lambda r: redirect(f"/hop{len(rec.requests)}"))
    with pytest.raises(DiscoveryFetchError, match="too many redirects"):
        client.get_json("https://api.example.com/start", max_bytes=1000, timeout=10)
    assert len(rec.requests) == 6  # the original request plus five followed redirects


def test_get_json_refuses_non_http_redirect():
    client, rec = make(lambda r: redirect("file:///etc/passwd"))
    with pytest.raises(DiscoveryFetchError):
        client.get_json("https://api.example.com/start", max_bytes=1000, timeout=10)
    assert len(rec.requests) == 1


# --- post_json ---------------------------------------------------------------


def test_post_json_sends_body():
    client, rec = make(lambda r: httpx.Response(200, json={"total": 0, "jobPostings": []}))
    body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}
    url = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/Site/jobs"
    result = client.post_json(url, body, max_bytes=1000, timeout=10)
    sent = rec.requests[0]
    assert sent.method == "POST"
    assert json.loads(sent.content) == body
    assert sent.headers["content-type"] == "application/json"
    assert sent.headers["user-agent"] == USER_AGENT
    assert result.data == {"total": 0, "jobPostings": []}


def test_post_json_does_not_follow_redirects():
    client, rec = make(lambda r: redirect("https://elsewhere.example/jobs"))
    with pytest.raises(DiscoveryFetchError) as info:
        client.post_json("https://api.example.com/jobs", {}, max_bytes=1000, timeout=10)
    assert info.value.status == 302
    assert len(rec.requests) == 1


# --- every call is address-checked and pinned --------------------------------


@pytest.mark.parametrize("method", ["get_json", "post_json"])
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/jobs",
        "http://localhost:5432/jobs",
        "http://10.0.0.5/jobs",
        "http://169.254.169.254/latest/meta-data",
        "http://internal.test/jobs",
        "http://mixed.test/jobs",
        "http://[::1]/jobs",
    ],
)
def test_json_calls_refuse_non_public_addresses_before_connecting(dns, method, url):
    # A list URL is user-configured and a board API can redirect, so the
    # guard cannot be limited to pasted pages.
    client, rec = make(lambda r: httpx.Response(200, json={}))
    call = {
        "get_json": lambda: client.get_json(url, max_bytes=1000, timeout=10),
        "post_json": lambda: client.post_json(url, {}, max_bytes=1000, timeout=10),
    }[method]
    with pytest.raises(DiscoveryFetchError, match="not allowed"):
        call()
    assert rec.requests == []


def test_get_json_connects_to_the_checked_address(dns):
    client, rec = make(lambda r: httpx.Response(200, json=[1]))
    result = client.get_json("https://api.example.com/jobs", max_bytes=1000, timeout=10)
    assert result.data == [1]
    assert result.final_url == "https://api.example.com/jobs"
    sent = rec.requests[0]
    assert sent.url.host == PUBLIC_V4
    assert sent.headers["host"] == "api.example.com"
    assert sent.extensions["sni_hostname"] == "api.example.com"


def test_post_json_connects_to_the_checked_address_and_keeps_the_body(dns):
    client, rec = make(lambda r: httpx.Response(200, json={"total": 0}))
    body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}
    url = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/Site/jobs"
    result = client.post_json(url, body, max_bytes=1000, timeout=10)
    sent = rec.requests[0]
    assert sent.method == "POST"
    assert json.loads(sent.content) == body
    assert sent.url.host == PUBLIC_V4
    assert sent.headers["host"] == "nvidia.wd5.myworkdayjobs.com"
    assert result.data == {"total": 0}


@pytest.mark.parametrize(
    "location",
    ["http://169.254.169.254/latest/meta-data", "http://internal.test/", "http://localhost/"],
)
def test_get_json_redirect_to_a_private_address_is_refused(dns, location):
    client, rec = make(lambda r: redirect(location))
    with pytest.raises(DiscoveryFetchError, match="not allowed"):
        client.get_json("https://api.example.com/jobs", max_bytes=1000, timeout=10)
    assert len(rec.requests) == 1


def test_get_json_tries_the_next_checked_address_on_connect_error(dns):
    def handler(request):
        if request.url.host == PUBLIC_V4:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=[2])

    client, rec = make(handler)
    result = client.get_json("https://multi.example/jobs", max_bytes=1000, timeout=10)
    assert result.data == [2]
    assert [r.url.host for r in rec.requests] == [PUBLIC_V4, PUBLIC_V4_B]


def test_get_json_unresolvable_host(dns):
    client, rec = make(lambda r: httpx.Response(200, json={}))
    with pytest.raises(DiscoveryFetchError, match="could not resolve host"):
        client.get_json("https://nowhere.invalid/jobs", max_bytes=1000, timeout=10)
    assert rec.requests == []


# --- get_page: SSRF guard ----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8000/admin",
        "http://localhost/",
        "http://localhost:5432/",
        "http://10.0.0.5/",
        "http://172.16.3.4/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest",
        "http://metadata.test/latest/meta-data",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://224.0.1.1/",
        "http://255.255.255.255/",
        "http://[::1]/",
        "http://[::]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://[fe80::1]/",
        "http://[fec0::1]/",
        "http://[fd00::1]/",
        "http://[ff02::1]/",
        "http://[2002:7f00:1::]/",
        "http://[2001:db8::1]/",
        "http://internal.test/",
        "http://fec0.example/",
        "http://mixed.test/",
        "http://2130706433/",
    ],
)
def test_get_page_refuses_non_public_addresses_before_connecting(dns, url):
    client, rec = make(lambda r: html())
    with pytest.raises(DiscoveryFetchError, match="not allowed"):
        client.get_page(url, max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert rec.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "gopher://example.com/",
        "/relative",
        "https://user:pass@example.com/",
        "https://example.com/" + "a" * 2000,
    ],
)
def test_get_page_refuses_bad_urls(dns, url):
    client, rec = make(lambda r: html())
    with pytest.raises(DiscoveryFetchError):
        client.get_page(url, max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert rec.requests == []
    assert dns == []


def test_get_page_unresolvable_host(dns):
    client, rec = make(lambda r: html())
    with pytest.raises(DiscoveryFetchError, match="resolve"):
        client.get_page("https://nowhere.invalid/", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert rec.requests == []


def test_get_page_connects_to_the_checked_address(dns):
    client, rec = make(lambda r: html("<title>Intern</title>", etag='"p"'))
    result = client.get_page("https://Example.com/jobs/1?x=1", max_bytes=PAGE_MAX_BYTES, timeout=10)
    sent = rec.requests[0]
    assert sent.url.host == PUBLIC_V4
    assert sent.url.scheme == "https"
    assert sent.url.raw_path == b"/jobs/1?x=1"
    assert sent.headers["host"] == "example.com"
    assert sent.extensions["sni_hostname"] == "example.com"
    assert sent.headers["user-agent"] == USER_AGENT
    assert dns == ["example.com"]
    assert result.status == 200
    assert result.text == "<title>Intern</title>"
    assert result.data is None
    assert result.etag == '"p"'
    assert result.final_url == "https://example.com/jobs/1?x=1"


def test_get_page_keeps_non_default_port_in_host_header(dns):
    client, rec = make(lambda r: html())
    client.get_page("http://example.com:8080/a", max_bytes=PAGE_MAX_BYTES, timeout=10)
    sent = rec.requests[0]
    assert (sent.url.host, sent.url.port) == (PUBLIC_V4, 8080)
    assert sent.headers["host"] == "example.com:8080"
    assert "sni_hostname" not in sent.extensions


def test_get_page_public_ipv6(dns):
    client, rec = make(lambda r: html())
    client.get_page("https://v6.example/", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert rec.requests[0].url.host == PUBLIC_V6
    assert rec.requests[0].headers["host"] == "v6.example"


def test_get_page_public_ip_literal_skips_dns(dns):
    client, rec = make(lambda r: html())
    client.get_page(f"http://{PUBLIC_V4}/", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert rec.requests[0].url.host == PUBLIC_V4
    assert dns == []


def test_get_page_redirect_to_loopback_is_refused(dns):
    client, rec = make(lambda r: redirect("http://127.0.0.1/admin"))
    with pytest.raises(DiscoveryFetchError, match="not allowed"):
        client.get_page("https://example.com/job", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert len(rec.requests) == 1


def test_get_page_redirect_to_private_hostname_is_refused(dns):
    client, rec = make(lambda r: redirect("http://internal.test/"))
    with pytest.raises(DiscoveryFetchError, match="not allowed"):
        client.get_page("https://example.com/job", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert len(rec.requests) == 1
    assert dns == ["example.com", "internal.test"]


def test_get_page_redirect_to_metadata_is_refused(dns):
    client, rec = make(lambda r: redirect("http://169.254.169.254/latest", status=301))
    with pytest.raises(DiscoveryFetchError, match="not allowed"):
        client.get_page("https://example.com/job", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert len(rec.requests) == 1


@pytest.mark.parametrize(
    "location", ["file:///etc/passwd", "ftp://example.com/", "javascript:alert(1)"]
)
def test_get_page_redirect_to_other_scheme_is_refused(dns, location):
    client, rec = make(lambda r: redirect(location))
    with pytest.raises(DiscoveryFetchError):
        client.get_page("https://example.com/job", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert len(rec.requests) == 1


def test_get_page_redirect_without_location(dns):
    client, _ = make(lambda r: httpx.Response(302))
    with pytest.raises(DiscoveryFetchError, match="redirect"):
        client.get_page("https://example.com/job", max_bytes=PAGE_MAX_BYTES, timeout=10)


def test_get_page_follows_relative_and_cross_host_redirects_rechecking_each(dns):
    def handler(request):
        host = request.headers["host"]
        if host == "example.com" and request.url.path == "/a":
            return redirect("/b", status=301)
        if host == "example.com" and request.url.path == "/b":
            return redirect("https://other.example/c", status=307)
        return html("<title>done</title>")

    client, rec = make(handler)
    result = client.get_page("https://example.com/a", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert result.text == "<title>done</title>"
    assert result.final_url == "https://other.example/c"
    assert [r.url.host for r in rec.requests] == [PUBLIC_V4, PUBLIC_V4, PUBLIC_V4_B]
    assert dns == ["example.com", "example.com", "other.example"]


def test_get_page_does_not_carry_cookies_across_hops(dns):
    def handler(request):
        if request.url.path == "/a":
            return redirect("/b", **{"set-cookie": "sid=abc; Path=/"})
        return html()

    client, rec = make(handler)
    client.get_page("https://example.com/a", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert "cookie" not in rec.requests[1].headers


def test_get_page_five_redirects_allowed(dns):
    def handler(request):
        n = len(rec.requests)
        return redirect(f"/hop{n}") if n <= 5 else html("<title>ok</title>")

    client, rec = make(handler)
    result = client.get_page("https://example.com/start", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert result.text == "<title>ok</title>"
    assert len(rec.requests) == 6


def test_get_page_more_than_five_redirects_raises(dns):
    client, rec = make(lambda r: redirect(f"/hop{len(rec.requests)}"))
    with pytest.raises(DiscoveryFetchError, match="too many redirects"):
        client.get_page("https://example.com/start", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert len(rec.requests) == 6


def test_get_page_too_large(dns):
    client, _ = make(lambda r: html("x" * 5000))
    with pytest.raises(DiscoveryFetchError, match="too large"):
        client.get_page("https://example.com/", max_bytes=1000, timeout=10)


def test_get_page_too_large_streamed(dns):
    def handler(request):
        return httpx.Response(
            200, content=chunks([b"<p>" + b"x" * 500] * 10), headers={"content-type": "text/html"}
        )

    client, _ = make(handler)
    with pytest.raises(DiscoveryFetchError, match="too large"):
        client.get_page("https://example.com/", max_bytes=1000, timeout=10)


@pytest.mark.parametrize("content_type", ["application/json", "application/pdf", "image/png", None])
def test_get_page_rejects_non_html(dns, content_type):
    headers = {"content-type": content_type} if content_type else {}
    client, _ = make(lambda r: httpx.Response(200, content=b"{}", headers=headers))
    with pytest.raises(DiscoveryFetchError, match="not a web page"):
        client.get_page("https://example.com/", max_bytes=PAGE_MAX_BYTES, timeout=10)


def test_get_page_accepts_xhtml_and_decodes_charset(dns):
    body = "<title>Café</title>".encode("latin-1")
    client, _ = make(
        lambda r: httpx.Response(
            200, content=body, headers={"content-type": "application/xhtml+xml; charset=ISO-8859-1"}
        )
    )
    result = client.get_page("https://example.com/", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert result.text == "<title>Café</title>"


def test_get_page_unknown_charset_falls_back_to_utf8(dns):
    client, _ = make(
        lambda r: httpx.Response(
            200, content="<p>é</p>".encode(), headers={"content-type": "text/html; charset=bogus-9"}
        )
    )
    result = client.get_page("https://example.com/", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert result.text == "<p>é</p>"


def test_get_page_error_status_carries_status_without_query(dns):
    client, _ = make(lambda r: html("denied", status=403))
    with pytest.raises(DiscoveryFetchError) as info:
        client.get_page("https://example.com/job?id=secret", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert info.value.status == 403
    assert "secret" not in str(info.value)
    assert "denied" not in str(info.value)


def test_get_page_treats_304_as_an_error(dns):
    client, _ = make(lambda r: httpx.Response(304))
    with pytest.raises(DiscoveryFetchError) as info:
        client.get_page("https://example.com/", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert info.value.status == 304


def test_get_page_tries_the_next_checked_address_on_connect_error(dns):
    def handler(request):
        if request.url.host == PUBLIC_V4:
            raise httpx.ConnectError("refused", request=request)
        return html("<title>second</title>")

    client, rec = make(handler)
    result = client.get_page("https://multi.example/", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert result.text == "<title>second</title>"
    assert [r.url.host for r in rec.requests] == [PUBLIC_V4, PUBLIC_V4_B]
    assert all(r.headers["host"] == "multi.example" for r in rec.requests)


def test_get_page_all_addresses_refusing_is_one_error(dns):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client, rec = make(handler)
    with pytest.raises(DiscoveryFetchError, match="ConnectError"):
        client.get_page("https://multi.example/", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert len(rec.requests) == 2


def test_get_page_non_connect_error_does_not_retry(dns):
    def handler(request):
        raise httpx.ReadError("reset", request=request)

    client, rec = make(handler)
    with pytest.raises(DiscoveryFetchError, match="ReadError"):
        client.get_page("https://multi.example/", max_bytes=PAGE_MAX_BYTES, timeout=10)
    assert len(rec.requests) == 1


def test_get_page_dns_lookup_is_bounded_by_the_deadline(monkeypatch):
    release = threading.Event()

    def hanging_getaddrinfo(*args, **kwargs):
        release.wait(5)
        raise socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")

    monkeypatch.setattr(socket, "getaddrinfo", hanging_getaddrinfo)
    client, rec = make(lambda r: html())
    started = time.monotonic()
    try:
        with pytest.raises(DiscoveryFetchError, match="timed out"):
            client.get_page("https://slow-dns.example/", max_bytes=PAGE_MAX_BYTES, timeout=0.3)
        assert time.monotonic() - started < 1.5
    finally:
        release.set()
    assert rec.requests == []


# --- real deadline against a local server that trickles headers --------------


@pytest.fixture()
def trickle_server():
    """A 127.0.0.1-only server that sends a status line and then one header
    byte every 50 ms forever, so every individual read succeeds well inside
    httpx's per-read timeout. Never leaves the machine."""
    stop = threading.Event()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.05)

    def trickle(conn: socket.socket) -> None:
        with conn:
            try:
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nX-Slow: ")
                while not stop.is_set():
                    conn.sendall(b"a")
                    stop.wait(0.05)
            except OSError:
                pass

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _addr = listener.accept()
            except (TimeoutError, OSError):
                continue
            threading.Thread(target=trickle, args=(conn,), daemon=True).start()

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    stop.set()
    server.join(2)
    listener.close()


@pytest.mark.parametrize("method", ["get_json", "post_json", "get_page"])
def test_deadline_holds_against_trickled_headers(monkeypatch, trickle_server, method):
    # Allow loopback for this test only, so get_page can reach the local server.
    monkeypatch.setattr(http_module, "_address_allowed", lambda ip: True)
    client = HttpxDiscoveryHttp()  # the real transport, on 127.0.0.1 only
    url = f"{trickle_server}/slow"
    call = {
        "get_json": lambda: client.get_json(url, max_bytes=PAGE_MAX_BYTES, timeout=1.0),
        "post_json": lambda: client.post_json(url, {}, max_bytes=PAGE_MAX_BYTES, timeout=1.0),
        "get_page": lambda: client.get_page(url, max_bytes=PAGE_MAX_BYTES, timeout=1.0),
    }[method]
    started = time.monotonic()
    with pytest.raises(DiscoveryFetchError, match="timed out"):
        call()
    elapsed = time.monotonic() - started
    assert 0.9 <= elapsed < 2.0


# --- FakeDiscoveryHttp -------------------------------------------------------


def test_fake_records_calls_and_scripts_responses():
    fake = FakeDiscoveryHttp(
        {
            ("GET", "https://a.test/l.json"): json_result([1], etag='"e"'),
            ("POST", "https://w.test/jobs"): [json_result({"p": 1}), json_result({"p": 2})],
            ("PAGE", "https://p.test/"): DiscoveryFetchError("p.test/: status 403", status=403),
        }
    )
    assert fake.get_json("https://a.test/l.json", etag=None, max_bytes=10, timeout=1).etag == '"e"'
    assert fake.post_json("https://w.test/jobs", {"offset": 0}, max_bytes=10, timeout=1).data == {
        "p": 1
    }
    assert fake.post_json("https://w.test/jobs", {"offset": 20}, max_bytes=10, timeout=1).data == {
        "p": 2
    }
    with pytest.raises(DiscoveryFetchError):
        fake.get_page("https://p.test/", max_bytes=10, timeout=1)
    with pytest.raises(UnexpectedRequestError):
        fake.get_json("https://unscripted.test/", max_bytes=10, timeout=1)
    assert [(c.method, c.url) for c in fake.calls] == [
        ("GET", "https://a.test/l.json"),
        ("POST", "https://w.test/jobs"),
        ("POST", "https://w.test/jobs"),
        ("PAGE", "https://p.test/"),
        ("GET", "https://unscripted.test/"),
    ]
    assert fake.calls[2].body == {"offset": 20}
