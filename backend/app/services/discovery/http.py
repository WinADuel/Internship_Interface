"""The one door job discovery uses to reach the network (Phase 2 spec §2, §9).

Everything goes through `DiscoveryHttp`, so tests pass a fake and never touch
the network. `HttpxDiscoveryHttp` is the real implementation.

SSRF guard for pasted pages (`get_page`, spec §2c): only http/https; every
hop's host must resolve only to public addresses; the request is then sent
to the address that passed the check (Host header and TLS SNI carry the
original name, and certificates are verified against it), so a second DNS
answer cannot swap in a private address between check and connect.
Redirects are followed by hand, at most five, each re-checked the same way.
"""

import ipaddress
import json
import socket
import time
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


@dataclass
class FetchResult:
    status: int  # 2xx, or 304 meaning "not modified" (data and text are None)
    data: Any | None  # parsed JSON (get_json/post_json)
    text: str | None  # decoded page (get_page)
    etag: str | None
    final_url: str  # after redirects, with the original host name


class DiscoveryFetchError(Exception):
    """One-line, user-safe failure: never a response body, never a query
    string (host + path only). `status` is set for an HTTP error status."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DiscoveryHttp(Protocol):
    """Implementations raise `DiscoveryFetchError` for transport failures,
    timeouts, any status other than 2xx/304, oversize bodies, invalid JSON
    and (get_page) refused addresses or non-HTML pages. A returned
    `FetchResult` therefore always has status 2xx or 304."""

    def get_json(
        self, url: str, *, etag: str | None = None, max_bytes: int, timeout: float
    ) -> FetchResult: ...

    def post_json(self, url: str, body: dict, *, max_bytes: int, timeout: float) -> FetchResult: ...

    def get_page(self, url: str, *, max_bytes: int, timeout: float) -> FetchResult: ...


def _where(url: httpx.URL | str) -> str:
    """host + path for messages and logs: never the query string."""
    try:
        parsed = url if isinstance(url, httpx.URL) else httpx.URL(url)
        where = f"{parsed.host}{parsed.path}"
    except (httpx.InvalidURL, TypeError, ValueError):
        where = "invalid url"
    return where[:_WHERE_MAX]


def _address_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # An IPv6 form that carries an IPv4 address must also carry a public one.
        for embedded in (ip.ipv4_mapped, ip.sixtofour):
            if embedded is not None and not _address_allowed(embedded):
                return False
    return True


def _resolve_public(host: str, port: int) -> tuple[str, bool]:
    """(address to connect to, host was an IP literal). Every address the
    name resolves to must be public, else DiscoveryFetchError."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _address_allowed(literal):
            raise DiscoveryFetchError(f"{host}: address not allowed")
        return str(literal), True
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise DiscoveryFetchError(f"{host}: could not resolve host") from None
    addresses = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            raise DiscoveryFetchError(f"{host}: address not allowed") from None
    if not addresses:
        raise DiscoveryFetchError(f"{host}: could not resolve host")
    if not all(_address_allowed(a) for a in addresses):
        raise DiscoveryFetchError(f"{host}: address not allowed")
    return str(addresses[0]), False


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


def _pinned_request(client: httpx.Client, url: httpx.URL) -> httpx.Request:
    """A GET for `url` sent to an address that passed the public-address check."""
    host = url.raw_host.decode("ascii")
    port = url.port or (443 if url.scheme == "https" else 80)
    address, is_literal = _resolve_public(host, port)
    if is_literal:
        return client.build_request("GET", url)
    headers = {"Host": f"{host}:{url.port}" if url.port else host}
    extensions = {"sni_hostname": host} if url.scheme == "https" else {}
    return client.build_request(
        "GET", url.copy_with(host=address), headers=headers, extensions=extensions
    )


def _read_capped(response: httpx.Response, max_bytes: int, deadline: float, where: str) -> bytes:
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > max_bytes:
        raise DiscoveryFetchError(f"{where}: too large")
    buffer = bytearray()
    for chunk in response.iter_bytes():
        buffer += chunk
        if len(buffer) > max_bytes:
            raise DiscoveryFetchError(f"{where}: too large")
        if time.monotonic() > deadline:
            raise DiscoveryFetchError(f"{where}: timed out")
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
    """`DiscoveryHttp` over httpx: streaming with a running byte count, a
    whole-request deadline, the project User-Agent, no cookies (the jar is
    cleared before every hop), no credentials, and no environment proxies or
    .netrc (`trust_env=False`). A fresh client per call keeps calls
    independent; tests inject an `httpx.MockTransport` (which must tolerate
    being closed after each call)."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(
            transport=self._transport,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": USER_AGENT},
        )

    def _fetch(
        self,
        method: str,
        url: str,
        *,
        max_bytes: int,
        timeout: float,
        headers: dict[str, str] | None = None,
        body: dict | None = None,
        follow_redirects: bool,
        guard: bool,
        page: bool,
    ) -> FetchResult:
        deadline = time.monotonic() + timeout
        current = _check_url(url)
        with self._client(timeout) as client:
            for _hop in range(MAX_REDIRECTS + 1):
                where = _where(current)
                client.cookies.clear()
                if guard:
                    request = _pinned_request(client, current)
                    request.headers.update(headers or {})
                else:
                    request = client.build_request(method, current, headers=headers, json=body)
                try:
                    response = client.send(request, stream=True)
                except (httpx.HTTPError, httpx.InvalidURL) as exc:
                    # httpx pre-builds the redirect request even when not
                    # following it, so a malformed Location raises InvalidURL here.
                    raise DiscoveryFetchError(
                        f"{where}: request failed ({type(exc).__name__})"
                    ) from None
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
                        if time.monotonic() > deadline:
                            raise DiscoveryFetchError(f"{where}: timed out")
                        continue
                    if status == 304:
                        etag = response.headers.get("etag") or (headers or {}).get("If-None-Match")
                        return FetchResult(304, None, None, etag, str(current))
                    if not 200 <= status < 300:
                        raise DiscoveryFetchError(f"{where}: status {status}", status=status)
                    if page:
                        content_type = response.headers.get("content-type", "")
                        if content_type.split(";", 1)[0].strip().lower() not in _PAGE_CONTENT_TYPES:
                            raise DiscoveryFetchError(f"{where}: not a web page")
                    try:
                        raw = _read_capped(response, max_bytes, deadline, where)
                    except httpx.HTTPError as exc:
                        raise DiscoveryFetchError(
                            f"{where}: request failed ({type(exc).__name__})"
                        ) from None
                    etag = response.headers.get("etag")
                    if page:
                        return FetchResult(
                            status, None, _decode_page(raw, response), etag, str(current)
                        )
                    return FetchResult(status, _parse_json(raw, where), None, etag, str(current))
                finally:
                    response.close()
        raise DiscoveryFetchError(f"{_where(url)}: too many redirects")

    def get_json(
        self, url: str, *, etag: str | None = None, max_bytes: int, timeout: float
    ) -> FetchResult:
        headers = {"Accept": "application/json"}
        if etag:
            headers["If-None-Match"] = etag
        return self._fetch(
            "GET",
            url,
            max_bytes=max_bytes,
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
            guard=False,
            page=False,
        )

    def post_json(self, url: str, body: dict, *, max_bytes: int, timeout: float) -> FetchResult:
        return self._fetch(
            "POST",
            url,
            max_bytes=max_bytes,
            timeout=timeout,
            headers={"Accept": "application/json"},
            body=body,
            follow_redirects=False,
            guard=False,
            page=False,
        )

    def get_page(self, url: str, *, max_bytes: int, timeout: float) -> FetchResult:
        return self._fetch(
            "GET",
            url,
            max_bytes=max_bytes,
            timeout=timeout,
            headers={"Accept": "text/html,application/xhtml+xml"},
            follow_redirects=True,
            guard=True,
            page=True,
        )
