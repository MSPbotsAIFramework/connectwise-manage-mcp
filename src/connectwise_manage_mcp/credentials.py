# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Per-request credentials, taken only from request headers.

The gateway sends each tenant's credentials on every request. They live in a
ContextVar for the duration of that request and are never stored anywhere else.

The middleware only checks that every required header is present. Formats
(site URL, company ID, keys) are checked inside the tools, because the platform
probes ``initialize`` and ``tools/list`` with placeholder header values.
"""

import contextvars
from dataclasses import dataclass, field

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import (
    CLIENT_ID_HEADER,
    COMPANY_ID_HEADER,
    PRIVATE_KEY_HEADER,
    PUBLIC_KEY_HEADER,
    REQUIRED_HEADERS,
    URL_HEADER,
)


@dataclass(frozen=True)
class Credentials:
    url: str
    company_id: str
    public_key: str = field(repr=False)
    private_key: str = field(repr=False)
    client_id: str = field(repr=False)


_current: contextvars.ContextVar[Credentials | None] = contextvars.ContextVar("cw_credentials", default=None)


def current() -> Credentials | None:
    return _current.get()


def _reject(missing: list[str]) -> JSONResponse:
    return JSONResponse(
        {
            "error": "Missing or invalid credentials",
            "message": f"Send your ConnectWise Manage credentials in these headers: {', '.join(missing)}.",
            "required_headers": REQUIRED_HEADERS,
            "missing_headers": missing,
        },
        status_code=401,
    )


class CredentialMiddleware:
    """Reads the ConnectWise headers on /mcp requests and binds them to the request context."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        values = {name: (request.headers.get(name) or "").strip() for name in REQUIRED_HEADERS}
        missing = [name for name, value in values.items() if not value]
        if missing:
            await _reject(missing)(scope, receive, send)
            return

        token = _current.set(
            Credentials(
                url=values[URL_HEADER],
                company_id=values[COMPANY_ID_HEADER],
                public_key=values[PUBLIC_KEY_HEADER],
                private_key=values[PRIVATE_KEY_HEADER],
                client_id=values[CLIENT_ID_HEADER],
            )
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)
