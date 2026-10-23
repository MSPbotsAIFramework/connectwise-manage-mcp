# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Thin async client for the ConnectWise PSA (Manage) REST API, version 3.0.

Reference: ConnectWise developer documentation (https://developer.connectwise.com/).
- Base URL ``https://<site>/<codebase>/apis/3.0``; the cloud codebase is ``v4_6_release``.
- Auth: HTTP Basic with ``<companyId>+<publicKey>`` as user and ``<privateKey>`` as password,
  plus a ``clientId`` header identifying the integration.
- Lists: ``page`` / ``pageSize`` (max 1000), ``conditions``, ``childConditions``, ``orderBy``, ``fields``.
  A ``Link`` header with ``rel="next"`` signals another page.
- Updates are JSON Patch arrays sent with PATCH.
"""

import asyncio
import base64
import email.utils
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import URL_HEADER, Settings
from .credentials import Credentials

DEFAULT_CODEBASE = "v4_6_release"
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_BACKOFF = 20.0
_HOST_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9-]{1,63}\.)+[A-Za-z0-9-]{1,63}$")
_API_PATH_RE = re.compile(r"^(.*?/apis/3\.0)(/.*)?$", re.IGNORECASE)


@dataclass
class ApiError(Exception):
    code: str
    message: str
    retryable: bool = False
    status: int | None = None

    def __str__(self) -> str:
        return self.message


def base_url(raw: str) -> str:
    """Normalise the site header to the API root.

    Accepts ``na.myconnectwise.net``, ``https://na.myconnectwise.net`` or a full
    ``https://na.myconnectwise.net/v4_6_release/apis/3.0`` (any codebase).
    """
    text = (raw or "").strip().rstrip("/")
    if not text:
        raise ApiError("not_configured", f"No ConnectWise site. Send the {URL_HEADER} header.")
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    host = parsed.hostname or ""
    if (
        parsed.scheme not in ("https", "http")
        or parsed.username
        or parsed.password
        or parsed.query
        or not _HOST_RE.match(host)
    ):
        raise ApiError(
            "invalid_argument",
            f"{URL_HEADER} must be a ConnectWise site such as https://na.myconnectwise.net (got an invalid value).",
        )
    path = parsed.path.rstrip("/")
    match = _API_PATH_RE.match(path)
    if match:
        path = match.group(1)
    else:
        path = f"{path}/{DEFAULT_CODEBASE}/apis/3.0"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _status_to_error(status: int, detail: str) -> ApiError:
    if status == 401:
        return ApiError(
            "unauthorized",
            (
                "ConnectWise rejected the credentials (401). "
                f"Check company ID, public/private key and client ID. {detail}"
            ).strip(),
            False,
            status,
        )
    if status == 403:
        return ApiError(
            "unauthorized",
            f"The API member's security role does not allow this (403). {detail}".strip(),
            False,
            status,
        )
    if status == 404:
        return ApiError("not_found", f"Not found in ConnectWise. {detail}".strip(), False, status)
    if status in (400, 405, 409, 415, 422):
        return ApiError(
            "invalid_argument", f"ConnectWise refused the request ({status}). {detail}".strip(), False, status
        )
    if status == 429:
        return ApiError("rate_limited", "ConnectWise rate limit reached. Try again shortly.", True, status)
    return ApiError("upstream_error", f"ConnectWise returned {status}. {detail}".strip(), status >= 500, status)


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    parts = []
    if body.get("code"):
        parts.append(str(body["code"]))
    if body.get("message"):
        parts.append(str(body["message"]))
    for err in (body.get("errors") or [])[:5]:
        if isinstance(err, dict):
            text = err.get("message") or err.get("code")
            if err.get("field"):
                text = f"{err['field']}: {text}"
            if text:
                parts.append(str(text))
    return "; ".join(parts)[:600]


def _retry_after(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("retry-after")
    if value:
        try:
            return max(0.0, min(float(value), MAX_BACKOFF))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                return max(0.0, min(parsed.timestamp() - time.time(), MAX_BACKOFF))
    return min(2.0**attempt, MAX_BACKOFF)


def _auth(creds: Credentials) -> str:
    raw = f"{creds.company_id}+{creds.public_key}:{creds.private_key}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


class CWClient:
    """One instance per tool call; wraps a single httpx client for that call."""

    def __init__(self, creds: Credentials, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._deadline = time.monotonic() + settings.call_budget_seconds
        self._http = httpx.AsyncClient(
            base_url=base_url(creds.url),
            headers={
                "Authorization": _auth(creds),
                "clientId": creds.client_id,
                "Accept": "application/json",
                "User-Agent": "mspbots-connectwise-manage-mcp/1.0",
            },
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
            transport=transport,
        )

    async def __aenter__(self) -> "CWClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    def time_left(self) -> float:
        return self._deadline - time.monotonic()

    async def send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        idempotent: bool | None = None,
    ) -> httpx.Response:
        """Send one request with retries.

        429 is always retried. 5xx and timeouts are retried only for idempotent
        requests (GET / PUT / DELETE by default), so a create is never duplicated.
        """
        if idempotent is None:
            idempotent = method.upper() in ("GET", "PUT", "DELETE", "HEAD")
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        attempt = 0
        while True:
            if self.time_left() <= 0:
                raise ApiError("upstream_error", "Time budget for this call ran out.", True)
            try:
                response = await self._http.request(method, path, params=clean, json=body)
            except httpx.TimeoutException as exc:
                if idempotent and attempt < self._settings.max_retries and self.time_left() > 1 + 2.0 ** (attempt + 1):
                    attempt += 1
                    await asyncio.sleep(min(2.0**attempt, MAX_BACKOFF))
                    continue
                raise ApiError("upstream_error", "ConnectWise did not respond in time.", True) from exc
            except httpx.HTTPError as exc:
                raise ApiError("upstream_error", f"Could not reach ConnectWise: {type(exc).__name__}.", True) from exc

            status = response.status_code
            retry = status == 429 or (idempotent and status in RETRY_STATUSES)
            if retry and attempt < self._settings.max_retries:
                wait = _retry_after(response, attempt + 1)
                if self.time_left() > wait + 1:
                    attempt += 1
                    await asyncio.sleep(wait)
                    continue
            if status >= 400:
                raise _status_to_error(status, _error_detail(response))
            return response

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self.send(method, path, **kwargs)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError("upstream_error", "ConnectWise returned a response that is not JSON.", True) from exc

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def get_page(self, path: str, params: dict[str, Any] | None = None) -> tuple[list[Any], bool | None]:
        """GET a list endpoint. Returns (rows, has_next) where has_next is None if unknown."""
        response = await self.send("GET", path, params=params)
        try:
            data = response.json() if response.content else []
        except ValueError as exc:
            raise ApiError("upstream_error", "ConnectWise returned a response that is not JSON.", True) from exc
        rows = data if isinstance(data, list) else [data]
        link = response.headers.get("link")
        has_next = None if link is None else ("next" in response.links)
        return rows, has_next

    async def get_all(
        self, path: str, params: dict[str, Any] | None = None, *, page_size: int = 1000, max_rows: int = 10000
    ) -> list[Any]:
        """Page through a list endpoint until it is exhausted or ``max_rows`` is reached."""
        out: list[Any] = []
        page = 1
        while len(out) < max_rows:
            rows, has_next = await self.get_page(path, {**(params or {}), "page": page, "pageSize": page_size})
            out.extend(rows)
            if has_next is False or (has_next is None and len(rows) < page_size) or not rows:
                break
            page += 1
        return out[:max_rows]

    async def post(self, path: str, body: Any, *, idempotent: bool | None = None) -> Any:
        return await self.request("POST", path, body=body, idempotent=idempotent)

    async def patch(self, path: str, operations: list[dict[str, Any]], *, idempotent: bool = False) -> Any:
        return await self.request("PATCH", path, body=operations, idempotent=idempotent)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)
