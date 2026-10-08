"""The one door job discovery uses to reach the network (Phase 2 spec §2, §9).

Everything goes through `DiscoveryHttp`, so tests pass a fake and never touch
the network. `HttpxDiscoveryHttp` is the real implementation.

SSRF guard for pasted pages (`get_page`, spec §2c): only http/https; every
hop's host must resolve only to public addresses; the request is then sent
to an address that passed the check (Host header and TLS SNI carry the
original name, and certificates are verified against it), so a second DNS
answer cannot swap in a private address between check and connect.
Redirects are followed by hand, at most five, each re-checked the same way.

Deadline: `timeout` bounds the whole call (DNS, connect, headers, body, every
redirect hop). httpx's own timeouts apply per read, so a server trickling one
byte at a time could otherwise hold a call (and a scan's advisory lock) for
hours. Each call therefore runs on its own event loop (`asyncio.run`) inside
`asyncio.timeout`, which really cancels a blocked read. The public methods
stay synchronous: FastAPI runs sync routes in a worker thread and the
job-scan loop is plain sync code; calling from inside a running event loop
is refused with a clear RuntimeError.
"""

import asyncio
import ipaddress
import json
import socket
import threading
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.services.discovery.urls import safe_http_url

USER_AGENT = "InternshipTracker/1.0 (personal job tracker)"
DEFAULT_TIMEOUT = 10.0
LIST_TIMEOUT = 30.0
LIST_MAX_BYTES = 50 * 1024 * 1024
PAGE_MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_PAGE_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_WHERE_MAX = 200

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass
class FetchResult:
    status: int  # 2xx, or 304 meaning "not modified" (data and text are None)
    data: Any | None  # parsed JSON (get_json/post_json)
    text: str | None  # decoded page (get_page)
    etag: str | None
    final_url: str  # after redirects, with the original host name


class DiscoveryFetchError(Exception):
    """One-line, user-safe failure: never a response body, never a query
    string (host + raw path only). `status` is set for an HTTP error status."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DiscoveryHttp(Protocol):
    """Implementations raise `DiscoveryFetchError` for transport failures,
    timeouts, any status other than 2xx (or 304 from get_json), oversize
    bodies, invalid JSON and (get_page) refused addresses or non-HTML pages.
    A returned `FetchResult` therefore always has status 2xx, or 304 from
    get_json called with an etag."""

    def get_json(
        self, url: str, *, etag: str | None = None, max_bytes: int, timeout: float
    ) -> FetchResult: ...

    def post_json(self, url: str, body: dict, *, max_bytes: int, timeout: float) -> FetchResult: ...

    def get_page(self, url: str, *, max_bytes: int, timeout: float) -> FetchResult: ...


def _clean(text: str) -> str:
    """Printable ASCII only, so a message is one line and safe to log."""
    return "".join(ch if 0x20 < ord(ch) < 0x7F else "?" for ch in text)


def _where(url: httpx.URL | str) -> str:
    """host + raw (still percent-encoded) path for messages and logs: never
    the query string, never a decoded CR/LF."""
    try:
        parsed = url if isinstance(url, httpx.URL) else httpx.URL(url)
        host = parsed.raw_host.decode("ascii", "replace")
        path = parsed.raw_path.split(b"?", 1)[0].decode("ascii", "replace")
        where = host + path
    except (httpx.InvalidURL, TypeError, ValueError):
        where = "invalid url"
    return _clean(where)[:_WHERE_MAX]


def _address_allowed(ip: IPAddress) -> bool:
    if (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)  # IPv6 fec0::/10; Python calls it global
    ):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # An IPv6 form that carries an IPv4 address must also carry a public one.
        for embedded in (ip.ipv4_mapped, ip.sixtofour):
            if embedded is not None and not _address_allowed(embedded):
                return False
    return True


async def _getaddrinfo(host: str, port: int) -> list:
    """socket.getaddrinfo in a daemon thread, awaitable and cancellable, so the
    caller's deadline bounds DNS too. A lookup the caller gave up on finishes
    in the background and is discarded; being a daemon thread, it never holds
    up `asyncio.run` shutdown or interpreter exit (the default executor would)."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    def settle(result: list | None, error: Exception | None) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    def work() -> None:
        try:
            result, error = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM), None
        except Exception as exc:  # noqa: BLE001 — handed back to the awaiting coroutine
            result, error = None, exc
        try:
            loop.call_soon_threadsafe(settle, result, error)
        except RuntimeError:
            pass  # the loop already closed: the caller timed out and left

    threading.Thread(target=work, name="discovery-dns", daemon=True).start()
    return await future


async def _resolve_public(host: str, port: int) -> tuple[list[str], bool]:
    """(addresses to try, in order; host was an IP literal). Every address the
    name resolves to must be public, else DiscoveryFetchError."""
    label = _clean(host)[:_WHERE_MAX]
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _address_allowed(literal):
            raise DiscoveryFetchError(f"{label}: address not allowed")
        return [str(literal)], True
    try:
        infos = await _getaddrinfo(host, port)
    except (OSError, UnicodeError):
        raise DiscoveryFetchError(f"{label}: could not resolve host") from None
    addresses: list[IPAddress] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            raise DiscoveryFetchError(f"{label}: address not allowed") from None
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise DiscoveryFetchError(f"{label}: could not resolve host")
    if not all(_address_allowed(a) for a in addresses):
        raise DiscoveryFetchError(f"{label}: address not allowed")
    return [str(a) for a in addresses], False


def _check_url(url: str) -> httpx.URL:
    """An absolute http(s) URL, ≤2000 chars, with no userinfo."""
    if safe_http_url(url) is None:
        raise DiscoveryFetchError("only http and https links can be fetched")
    try:
        parsed = httpx.URL(url.strip())
    except httpx.InvalidURL:
        raise DiscoveryFetchError("invalid url") from None
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise DiscoveryFetchError("only http and https links can be fetched")
    if parsed.userinfo:
        raise DiscoveryFetchError(f"{_where(parsed)}: links with credentials are not allowed")
    return parsed


def _request_failed(where: str, exc: BaseException) -> DiscoveryFetchError:
    return DiscoveryFetchError(f"{where}: request failed ({type(exc).__name__})")


async def _send(client: httpx.AsyncClient, request: httpx.Request, where: str) -> httpx.Response:
    try:
        return await client.send(request, stream=True)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        # httpx pre-builds the redirect request even when not following it,
        # so a malformed Location raises InvalidURL here.
        raise _request_failed(where, exc) from None


async def _send_pinned(
    client: httpx.AsyncClient, url: httpx.URL, headers: dict[str, str], where: str
) -> httpx.Response:
    """GET `url` from an address that passed the public-address check, trying
    the next checked address when one refuses the connection."""
    host = url.raw_host.decode("ascii")
    port = url.port or (443 if url.scheme == "https" else 80)
    addresses, is_literal = await _resolve_public(host, port)
    if is_literal:
        return await _send(client, client.build_request("GET", url, headers=headers), where)
    pinned_headers = {**headers, "Host": f"{host}:{url.port}" if url.port else host}
    extensions = {"sni_hostname": host} if url.scheme == "https" else {}
    last_error: Exception | None = None
    for address in addresses:
        request = client.build_request(
            "GET", url.copy_with(host=address), headers=pinned_headers, extensions=extensions
        )
        try:
            return await client.send(request, stream=True)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_error = exc
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise _request_failed(where, exc) from None
    assert last_error is not None
    raise _request_failed(where, last_error)


async def _read_capped(response: httpx.Response, max_bytes: int, where: str) -> bytes:
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > max_bytes:
        raise DiscoveryFetchError(f"{where}: too large")
    buffer = bytearray()
    try:
        async for chunk in response.aiter_bytes():
            buffer += chunk
            if len(buffer) > max_bytes:
                raise DiscoveryFetchError(f"{where}: too large")
    except httpx.HTTPError as exc:
        raise _request_failed(where, exc) from None
    return bytes(buffer)


def _parse_json(raw: bytes, where: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        raise DiscoveryFetchError(f"{where}: invalid json") from None


def _decode_page(raw: bytes, response: httpx.Response) -> str:
    encoding = response.charset_encoding or "utf-8"
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


class HttpxDiscoveryHttp:
    """`DiscoveryHttp` over httpx: streaming with a running byte count, one
    deadline for the whole call, the project User-Agent, no cookies (the jar
    is cleared before every hop), no credentials, and no environment proxies
    or .netrc (`trust_env=False`). Each call gets a fresh client and event
    loop; tests inject an `httpx.MockTransport` (async-capable, and it must
    tolerate being closed after each call)."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": USER_AGENT},
        )

    def _run(self, url: str, timeout: float, **kwargs: Any) -> FetchResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "HttpxDiscoveryHttp is synchronous: call it from a worker thread, "
                "not from inside a running event loop"
            )
        return asyncio.run(self._fetch(url, timeout, **kwargs))

    async def _fetch(self, url: str, timeout: float, **kwargs: Any) -> FetchResult:
        progress = {"where": _where(url)}
        try:
            async with asyncio.timeout(timeout):
                return await self._hops(url, timeout, progress, **kwargs)
        except TimeoutError:
            raise DiscoveryFetchError(f"{progress['where']}: timed out") from None

    async def _hops(
        self,
        url: str,
        timeout: float,
        progress: dict[str, str],
        *,
        method: str,
        max_bytes: int,
        headers: dict[str, str],
        body: dict | None = None,
        follow_redirects: bool,
        guard: bool,
        page: bool,
    ) -> FetchResult:
        current = _check_url(url)
        async with self._client(timeout) as client:
            for _hop in range(MAX_REDIRECTS + 1):
                where = progress["where"] = _where(current)
                client.cookies.clear()
                if guard:
                    response = await _send_pinned(client, current, headers, where)
                else:
                    request = client.build_request(method, current, headers=headers, json=body)
                    response = await _send(client, request, where)
                try:
                    status = response.status_code
                    if follow_redirects and status in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise DiscoveryFetchError(f"{where}: redirect without a location")
                        try:
                            target = str(current.join(location))
                        except httpx.InvalidURL:
                            raise DiscoveryFetchError(f"{where}: invalid redirect") from None
                        current = _check_url(target)
                        continue
                    # A 304 only answers a conditional request, which get_page never sends.
                    if status == 304 and not page:
                        etag = response.headers.get("etag") or headers.get("If-None-Match")
                        return FetchResult(304, None, None, etag, str(current))
                    if not 200 <= status < 300:
                        raise DiscoveryFetchError(f"{where}: status {status}", status=status)
                    if page:
                        content_type = response.headers.get("content-type", "")
                        if content_type.split(";", 1)[0].strip().lower() not in _PAGE_CONTENT_TYPES:
                            raise DiscoveryFetchError(f"{where}: not a web page")
                    raw = await _read_capped(response, max_bytes, where)
                    etag = response.headers.get("etag")
                    if page:
                        text = _decode_page(raw, response)
                        return FetchResult(status, None, text, etag, str(current))
                    return FetchResult(status, _parse_json(raw, where), None, etag, str(current))
                finally:
                    await response.aclose()
        raise DiscoveryFetchError(f"{_where(url)}: too many redirects")

    def get_json(
        self, url: str, *, etag: str | None = None, max_bytes: int, timeout: float
    ) -> FetchResult:
        headers = {"Accept": "application/json"}
        if etag:
            headers["If-None-Match"] = etag
        return self._run(
            url,
            timeout,
            method="GET",
            max_bytes=max_bytes,
            headers=headers,
            follow_redirects=True,
            guard=False,
            page=False,
        )

    def post_json(self, url: str, body: dict, *, max_bytes: int, timeout: float) -> FetchResult:
        return self._run(
            url,
            timeout,
            method="POST",
            max_bytes=max_bytes,
            headers={"Accept": "application/json"},
            body=body,
            follow_redirects=False,
            guard=False,
            page=False,
        )

    def get_page(self, url: str, *, max_bytes: int, timeout: float) -> FetchResult:
        return self._run(
            url,
            timeout,
            method="GET",
            max_bytes=max_bytes,
            headers={"Accept": "text/html,application/xhtml+xml"},
            follow_redirects=True,
            guard=True,
            page=True,
        )
