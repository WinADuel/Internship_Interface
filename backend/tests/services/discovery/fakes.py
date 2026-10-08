"""Test double for `DiscoveryHttp`: no test in this package touches the network."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.services.discovery.http import FetchResult


@dataclass(frozen=True)
class FakeCall:
    method: str  # "GET" (get_json), "POST" (post_json) or "PAGE" (get_page)
    url: str
    body: dict | None = None
    etag: str | None = None
    max_bytes: int | None = None
    timeout: float | None = None


class UnexpectedRequestError(AssertionError):
    """Raised for a request the test did not script. Subclasses AssertionError
    so a source that swallows ordinary exceptions still fails loudly if it
    re-raises assertions; tests should also check `calls`."""


Response = FetchResult | BaseException | Callable[[FakeCall], FetchResult]


class FakeDiscoveryHttp:
    """Maps `(method, url)` to a `FetchResult`, an exception to raise, a
    callable `(FakeCall) -> FetchResult` (e.g. to page through Workday POST
    bodies), or a list of those consumed one per call. Records every call."""

    def __init__(self, responses: dict[tuple[str, str], Response | list[Response]] | None = None):
        self.responses: dict[tuple[str, str], Any] = dict(responses or {})
        self.calls: list[FakeCall] = []

    def add(self, method: str, url: str, response: Response | list[Response]) -> None:
        self.responses[(method, url)] = response

    def _respond(self, call: FakeCall) -> FetchResult:
        self.calls.append(call)
        key = (call.method, call.url)
        if key not in self.responses:
            raise UnexpectedRequestError(f"unscripted request: {call.method} {call.url}")
        response = self.responses[key]
        if isinstance(response, list):
            if not response:
                raise UnexpectedRequestError(
                    f"no more scripted responses: {call.method} {call.url}"
                )
            response = response.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(call)
        return response

    def get_json(
        self, url: str, *, etag: str | None = None, max_bytes: int, timeout: float
    ) -> FetchResult:
        return self._respond(FakeCall("GET", url, etag=etag, max_bytes=max_bytes, timeout=timeout))

    def post_json(self, url: str, body: dict, *, max_bytes: int, timeout: float) -> FetchResult:
        return self._respond(FakeCall("POST", url, body=body, max_bytes=max_bytes, timeout=timeout))

    def get_page(self, url: str, *, max_bytes: int, timeout: float) -> FetchResult:
        return self._respond(FakeCall("PAGE", url, max_bytes=max_bytes, timeout=timeout))


def json_result(
    data: Any, *, url: str = "https://example.test/", etag: str | None = None
) -> FetchResult:
    return FetchResult(status=200, data=data, text=None, etag=etag, final_url=url)


def page_result(text: str, *, url: str) -> FetchResult:
    return FetchResult(status=200, data=None, text=text, etag=None, final_url=url)
