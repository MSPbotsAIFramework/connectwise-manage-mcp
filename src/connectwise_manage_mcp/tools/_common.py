# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Shared plumbing for tool handlers."""

import copy
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .. import _json
from ..api import ApiError, CWClient
from ..config import REQUIRED_HEADERS, Settings
from ..credentials import current

log = logging.getLogger("connectwise_manage_mcp")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
CREATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
UPDATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)

Page = Annotated[int | None, Field(description="Page number (default: 1).", ge=1)]
Conditions = Annotated[
    str | None,
    Field(description='ConnectWise conditions query string, e.g. name like "%Acme%". Strings use double quotes.'),
]
OrderBy = Annotated[str | None, Field(description="Field to order by, e.g. 'id desc'.")]
Fields = Annotated[
    str | None,
    Field(description="Optional comma-separated list of fields to return (e.g. 'id,name'), to keep results small."),
]


def page_size_param(default: int = DEFAULT_PAGE_SIZE):
    return Annotated[
        int | None,
        Field(description=f"Results per page (default: {default}, max: {MAX_PAGE_SIZE}).", ge=1),
    ]


PageSize = page_size_param()


def paging(page: int | None, page_size: int | None, default: int = DEFAULT_PAGE_SIZE) -> tuple[int, int]:
    size = min(max(int(page_size or default), 1), MAX_PAGE_SIZE)
    return max(int(page or 1), 1), size


class ToolInputError(ValueError):
    """Raised by handlers for arguments ConnectWise would reject anyway."""


Handler = Callable[[CWClient], Awaitable[Any]]


async def run(settings: Settings, handler: Handler) -> str:
    """Execute ``handler`` with a client bound to this request's credentials.

    Always returns a string: the JSON result, or an error envelope.
    """
    creds = current()
    if creds is None:
        return _json.error(
            "not_configured", f"No ConnectWise credentials. Send the headers: {', '.join(REQUIRED_HEADERS)}."
        )
    try:
        async with CWClient(creds, settings) as client:
            result = await handler(client)
    except ApiError as exc:
        return _json.error(exc.code, exc.message, exc.retryable)
    except ToolInputError as exc:
        return _json.error("invalid_argument", str(exc))
    except Exception:  # noqa: BLE001 - tools must never raise
        log.exception("unexpected error in tool handler")
        return _json.error("upstream_error", "Unexpected error while calling ConnectWise.", True)
    return result if isinstance(result, str) else _json.dump(result)


# ---- small helpers ----------------------------------------------------------


def seg(value: object) -> str:
    """Path segment for an ID. Only positive whole numbers are accepted, so IDs cannot alter the URL path."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if not text.isdigit() or int(text) <= 0:
        raise ToolInputError(f"Expected a positive numeric ID, got {text!r}.")
    return text


def ref(value: Any) -> dict[str, Any] | None:
    """``5`` -> ``{"id": 5}``; ``None`` stays ``None``."""
    if value is None:
        return None
    return {"id": int(seg(value))}


def body(**values: Any) -> dict[str, Any]:
    """Request body without unset values."""
    return {k: v for k, v in values.items() if v is not None}


def clean(data: Any, top: bool = True) -> Any:
    """Drop the ``*_href`` links ConnectWise adds to every object.

    Nested references lose their ``_info`` block entirely (it only carries links);
    a record's own ``_info`` keeps dates and authors.
    """
    if isinstance(data, list):
        return [clean(v, top) for v in data]
    if not isinstance(data, dict):
        return data
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(key, str) and key.endswith("_href"):
            continue
        if key == "_info":
            if not top or not isinstance(value, dict):
                continue
            value = clean(value, False)
            if not value:
                continue
        else:
            value = clean(value, False)
        out[key] = value
    return out


def list_result(rows: list[Any], page: int, size: int, has_next: bool | None) -> dict[str, Any]:
    items = clean(rows)
    return {
        "items": items,
        "count": len(items),
        "page": page,
        "page_size": size,
        "has_more": has_next if has_next is not None else len(rows) >= size,
    }


def _requote(text: str) -> str:
    """ConnectWise wants string literals in double quotes; turn 'x' literals into "x"."""
    out: list[str] = []
    i, n = 0, len(text)
    in_double = False
    while i < n:
        ch = text[i]
        if ch == '"':
            in_double = not in_double
            out.append(ch)
        elif ch == "'" and not in_double:
            end = text.find("'", i + 1)
            if end == -1:
                out.append(text[i:])
                break
            inner = text[i + 1 : end]
            if '"' in inner:
                out.append(text[i : end + 1])
            else:
                out.append(f'"{inner}"')
            i = end
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def join_conditions(*parts: str | None) -> str | None:
    """AND together condition fragments, normalising quotes."""
    items = [_requote(p.strip()) for p in parts if p and p.strip()]
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return " and ".join(f"({p})" for p in items)


def quote(value: str) -> str:
    """A safe double-quoted ConnectWise string literal."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---- JSON Patch ---------------------------------------------------------------


class PatchOp(BaseModel):
    op: Literal["replace", "add", "remove"] = Field(description="Patch operation")
    path: str = Field(description="Field path, e.g. 'summary' or 'status/id'")
    value: Any = Field(default=None, description="New value (required for add and replace; unused for remove)")


# No min_length here (PRD-21611): a schema-level minItems=1 makes FastMCP reject an empty list with a raw
# ToolError before any handler runs, bypassing the structured error envelope. patch_ops() below already
# rejects an empty list with ToolInputError -> {"error": {"code": "invalid_argument"}}; that is the one
# enforcement path, so every *_update_* tool using Operations returns a consistent envelope.
Operations = Annotated[list[PatchOp], Field(description="Array of JSON Patch operations")]

_PATH_RE = re.compile(r"^/?[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*$")


def patch_ops(operations: list[PatchOp] | list[dict], *, value_required: bool = True) -> tuple[list[dict], bool]:
    """Validate patch operations. Returns (operations, replace_only)."""
    if not operations:
        raise ToolInputError("operations must contain at least one operation.")
    out: list[dict] = []
    for raw in operations:
        op = raw if isinstance(raw, PatchOp) else PatchOp.model_validate(raw)
        path = op.path.strip()
        if not _PATH_RE.match(path):
            raise ToolInputError(f"Invalid patch path {op.path!r}.")
        item: dict[str, Any] = {"op": op.op, "path": path}
        if op.op != "remove":
            if value_required and op.value is None and "value" not in op.model_fields_set:
                raise ToolInputError(f"Operation {op.op} on {path} needs a value.")
            item["value"] = op.value
        out.append(item)
    return out, all(o["op"] == "replace" for o in out)


def apply_patch(document: dict[str, Any], operations: list[dict]) -> dict[str, Any]:
    """Apply JSON Patch operations locally (for dry runs). Paths use '/' and may omit the leading slash."""
    doc = copy.deepcopy(document)
    for op in operations:
        keys = [k for k in op["path"].strip("/").split("/") if k]
        target: Any = doc
        for key in keys[:-1]:
            if isinstance(target, list):
                target = target[int(key)]
            else:
                if not isinstance(target.get(key), dict | list):
                    target[key] = {}
                target = target[key]
        last = keys[-1]
        if isinstance(target, list):
            if op["op"] == "remove":
                target.pop(int(last))
            elif last == "-":
                target.append(op["value"])
            elif op["op"] == "add":
                target.insert(int(last), op["value"])
            else:
                target[int(last)] = op["value"]
        elif op["op"] == "remove":
            target.pop(last, None)
        else:
            target[last] = op["value"]
    return doc


# ---- tool factories -------------------------------------------------------------


def add_search(
    mcp: FastMCP,
    settings: Settings,
    *,
    name: str,
    description: str,
    path: str,
    conditions_help: str = "ConnectWise conditions query string",
    order_help: str = "Field to order by (e.g. 'id desc')",
) -> None:
    """Register a list tool with the standard conditions / page / pageSize / orderBy parameters."""

    @mcp.tool(name=name, description=description, annotations=READ, structured_output=False)
    async def search(
        conditions: Annotated[str | None, Field(description=conditions_help)] = None,
        page: Page = None,
        pageSize: PageSize = None,
        orderBy: Annotated[str | None, Field(description=order_help)] = None,
        fields: Fields = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            params = {
                "conditions": join_conditions(conditions),
                "orderBy": orderBy,
                "fields": fields,
                "page": number,
                "pageSize": size,
            }
            rows, has_next = await client.get_page(path, params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)


def add_get(mcp: FastMCP, settings: Settings, *, name: str, description: str, path: str, id_help: str) -> None:
    """Register a get-by-ID tool. ``path`` contains ``{id}``."""

    @mcp.tool(name=name, description=description, annotations=READ, structured_output=False)
    async def get(id: Annotated[int, Field(description=id_help)]) -> str:
        async def handler(client: CWClient):
            return clean(await client.get(path.format(id=seg(id))))

        return await run(settings, handler)
