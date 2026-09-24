"""Read-only transport abstractions for Space-Track.

Authentication is intentionally injected by the caller. The canonical core
does not know usernames, passwords, cookies, or write/upload endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.request import OpenerDirector, Request, build_opener


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


class ReadOnlyTransport(Protocol):
    def get(self, url: str) -> TransportResponse:
        ...


class UrlLibReadOnlyTransport:
    """Minimal GET-only transport.

    A pre-authenticated cookie-capable opener may be injected at runtime after
    credentials are provisioned outside the repository.
    """

    def __init__(
        self,
        opener: OpenerDirector | None = None,
        *,
        timeout_seconds: float = 30.0,
        user_agent: str = "skywatcher-pr/space-track-read-only-v1",
    ) -> None:
        self._opener = opener or build_opener()
        self._timeout_seconds = timeout_seconds
        self._user_agent = user_agent

    def get(self, url: str) -> TransportResponse:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self._user_agent,
            },
            method="GET",
        )
        with self._opener.open(request, timeout=self._timeout_seconds) as response:
            status = int(getattr(response, "status", response.getcode()))
            headers = {str(k): str(v) for k, v in response.headers.items()}
            return TransportResponse(status=status, body=response.read(), headers=headers)
