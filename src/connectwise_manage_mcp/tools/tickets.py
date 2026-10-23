# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Service tickets, their notes and configuration associations."""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from ..api import ApiError, CWClient
from ..config import Settings
from ._common import (
    CREATE,
    DESTRUCTIVE,
    READ,
    UPDATE,
    Operations,
    Page,
    PageSize,
    ToolInputError,
    add_get,
    add_search,
    body,
    clean,
    join_conditions,
    list_result,
    paging,
    patch_ops,
    ref,
    run,
    seg,
)

CHILD_TICKET_LIMIT = 10


class ConfigurationChange(BaseModel):
    action: Literal["add", "remove"] = Field(description="Add or remove the ticket association")
    configurationId: int = Field(description="Existing configuration object ID", gt=0)


def note_flags(detail: bool | None, internal: bool | None, resolution: bool | None) -> dict[str, bool]:
    """ConnectWise needs at least one of the three note flags; default to a discussion note."""
    if not (detail or internal or resolution):
        detail = True
    return {
        "detailDescriptionFlag": bool(detail),
        "internalAnalysisFlag": bool(internal),
        "resolutionFlag": bool(resolution),
    }


async def notes_with_children(
    client: CWClient, ticket_path: str, ticket_id: str, page: int, size: int
) -> dict[str, Any]:
    """Notes of one ticket; on page 1 also the first notes page of up to 10 child tickets."""
    rows, has_next = await client.get_page(
        f"{ticket_path}/{ticket_id}/notes", {"page": page, "pageSize": size, "orderBy": "id asc"}
    )
    result = list_result(rows, page, size, has_next)
    if page != 1:
        return result
    try:
        children, _ = await client.get_page(
            ticket_path,
            {"conditions": f"parentTicketId = {ticket_id}", "fields": "id,summary", "pageSize": CHILD_TICKET_LIMIT},
        )
    except ApiError as exc:
        if exc.code != "invalid_argument":
            raise
        return result
    child_notes = []
    for child in children:
        child_id = seg(child.get("id"))
        notes, more = await client.get_page(
            f"{ticket_path}/{child_id}/notes", {"page": 1, "pageSize": size, "orderBy": "id asc"}
        )
        child_notes.append(
            {
                "ticketId": int(child_id),
                "summary": child.get("summary"),
                "notes": clean(notes),
                "has_more": more if more is not None else len(notes) >= size,
            }
        )
    if child_notes:
        result["child_tickets"] = child_notes
    return result


def register(mcp: FastMCP, settings: Settings) -> None:
    add_search(
        mcp,
        settings,
        name="cw_search_tickets",
        description=(
            "Search service tickets in ConnectWise Manage. Use 'conditions' for CW query syntax, e.g. "
            'status/name != "Closed" or company/name = "Acme" (single quotes are converted).'
        ),
        path="/service/tickets",
    )
    add_get(
        mcp,
        settings,
        name="cw_get_ticket",
        description="Get a specific service ticket by ID.",
        path="/service/tickets/{id}",
        id_help="Ticket ID",
    )

    @mcp.tool(
        name="cw_create_ticket",
        description=(
            "Create a new service ticket. Set parentTicketId to create it as a child of another ticket. "
            "Look up board, status, priority and type IDs with cw_list_boards, cw_list_statuses and "
            "cw_list_priorities."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_create_ticket(
        summary: Annotated[str, Field(description="Ticket summary/title (max 100 characters)")],
        boardId: Annotated[int | None, Field(description="Service board ID")] = None,
        companyId: Annotated[int | None, Field(description="Company ID to associate")] = None,
        contactId: Annotated[int | None, Field(description="Contact ID to associate")] = None,
        statusId: Annotated[int | None, Field(description="Status ID")] = None,
        priorityId: Annotated[int | None, Field(description="Priority ID")] = None,
        typeId: Annotated[int | None, Field(description="Type ID")] = None,
        subTypeId: Annotated[int | None, Field(description="SubType ID")] = None,
        initialDescription: Annotated[str | None, Field(description="Initial ticket description")] = None,
        parentTicketId: Annotated[
            int | None,
            Field(description="Parent ticket ID; the new ticket becomes its child. Omit to leave unparented."),
        ] = None,
    ) -> str:
        async def handler(client: CWClient):
            if not summary.strip():
                raise ToolInputError("summary must not be empty.")
            payload = body(
                summary=summary,
                board=ref(boardId),
                company=ref(companyId),
                contact=ref(contactId),
                status=ref(statusId),
                priority=ref(priorityId),
                type=ref(typeId),
                subType=ref(subTypeId),
                initialDescription=initialDescription,
                parentTicketId=int(seg(parentTicketId)) if parentTicketId is not None else None,
            )
            return clean(await client.post("/service/tickets", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_update_ticket",
        description=(
            "Update an existing service ticket using JSON Patch operations, e.g. "
            "[{op: 'replace', path: 'status/id', value: 5}] or path 'summary'."
        ),
        annotations=UPDATE,
        structured_output=False,
    )
    async def cw_update_ticket(
        id: Annotated[int, Field(description="Ticket ID")],
        operations: Operations,
    ) -> str:
        async def handler(client: CWClient):
            ops, replace_only = patch_ops(operations)
            return clean(await client.patch(f"/service/tickets/{seg(id)}", ops, idempotent=replace_only))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_get_ticket_notes",
        description=(
            "Get notes on a service ticket, oldest first. Page 1 also lists notes of up to 10 child tickets "
            "under child_tickets."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_get_ticket_notes(
        id: Annotated[int, Field(description="Ticket ID")],
        page: Page = None,
        pageSize: PageSize = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            return await notes_with_children(client, "/service/tickets", seg(id), number, size)

        return await run(settings, handler)

    @mcp.tool(
        name="cw_add_ticket_note",
        description=(
            "Add a note to a service ticket: detailDescriptionFlag (discussion, the default), "
            "internalAnalysisFlag (internal only) or resolutionFlag. Nobody is emailed unless you set "
            "emailContactFlag, emailResourceFlag or emailCcFlag (with emailCc). processNotifications is sent "
            "as true only when an email flag is true, unless you set it yourself; false suppresses delivery."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_add_ticket_note(
        id: Annotated[int, Field(description="Ticket ID")],
        text: Annotated[str, Field(description="Note text content")],
        detailDescriptionFlag: Annotated[
            bool | None, Field(description="Discussion note (default when no flag)")
        ] = None,
        internalAnalysisFlag: Annotated[
            bool | None, Field(description="Internal analysis only (default: false)")
        ] = None,
        resolutionFlag: Annotated[bool | None, Field(description="Resolution note (default: false)")] = None,
        customerUpdatedFlag: Annotated[
            bool | None, Field(description="Flag that the customer was updated (default: false)")
        ] = None,
        emailContactFlag: Annotated[
            bool | None, Field(description="Email the ticket contact. Never defaults to true.")
        ] = None,
        emailResourceFlag: Annotated[
            bool | None, Field(description="Email ticket resources. Never defaults to true.")
        ] = None,
        emailCcFlag: Annotated[
            bool | None, Field(description="Email the addresses in emailCc. Never defaults to true.")
        ] = None,
        emailCc: Annotated[
            str | None, Field(description="CC email addresses. Nobody is emailed unless emailCcFlag is true.")
        ] = None,
        processNotifications: Annotated[
            bool | None,
            Field(description="Force notification processing on or off. Omit to derive it from the email flags."),
        ] = None,
    ) -> str:
        async def handler(client: CWClient):
            if not text.strip():
                raise ToolInputError("text must not be empty.")
            payload: dict[str, Any] = {
                "text": text,
                **note_flags(detailDescriptionFlag, internalAnalysisFlag, resolutionFlag),
            }
            payload.update(
                body(
                    customerUpdatedFlag=customerUpdatedFlag,
                    emailContactFlag=emailContactFlag,
                    emailResourceFlag=emailResourceFlag,
                    emailCcFlag=emailCcFlag,
                    emailCc=emailCc,
                )
            )
            notify = processNotifications
            if notify is None and (emailContactFlag or emailResourceFlag or emailCcFlag):
                notify = True
            if notify is not None:
                payload["processNotifications"] = notify
            return clean(await client.post(f"/service/tickets/{seg(id)}/notes", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_get_ticket_configurations",
        description=(
            "Get configuration references associated with a service ticket, one page at a time "
            "(default: page 1, 25 results). Returns id and deviceIdentifier; use cw_get_configuration for details."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_get_ticket_configurations(
        id: Annotated[int, Field(description="Service ticket ID", gt=0)],
        page: Page = None,
        pageSize: PageSize = None,
        conditions: Annotated[str | None, Field(description="ConnectWise conditions query string")] = None,
        orderBy: Annotated[str | None, Field(description="Field to order by (e.g. 'id asc')")] = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            params = {
                "page": number,
                "pageSize": size,
                "conditions": join_conditions(conditions),
                "orderBy": orderBy,
            }
            rows, has_next = await client.get_page(f"/service/tickets/{seg(id)}/configurations", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    @mcp.tool(
        name="cw_update_ticket_configurations",
        description=(
            "Add or remove configuration associations on a service ticket. Operations run in order; removing an "
            "association leaves the configuration intact. Continues after individual failures without rollback "
            "and returns each operation's outcome, with failed > 0 if any failed."
        ),
        annotations=DESTRUCTIVE,
        structured_output=False,
    )
    async def cw_update_ticket_configurations(
        id: Annotated[int, Field(description="Service ticket ID", gt=0)],
        operations: Annotated[
            list[ConfigurationChange],
            Field(description="Nonempty ordered list of configuration association changes", min_length=1),
        ],
    ) -> str:
        async def handler(client: CWClient):
            ticket = seg(id)
            results = []
            for change in operations:
                config = seg(change.configurationId)
                try:
                    if change.action == "add":
                        await client.post(f"/service/tickets/{ticket}/configurations", {"id": int(config)})
                    else:
                        await client.delete(f"/service/tickets/{ticket}/configurations/{config}")
                    results.append({"action": change.action, "configurationId": int(config), "success": True})
                except ApiError as exc:
                    results.append(
                        {
                            "action": change.action,
                            "configurationId": int(config),
                            "success": False,
                            "error": {"code": exc.code, "message": exc.message},
                        }
                    )
            failed = sum(1 for r in results if not r["success"])
            return {"ticketId": int(ticket), "results": results, "succeeded": len(results) - failed, "failed": failed}

        return await run(settings, handler)
