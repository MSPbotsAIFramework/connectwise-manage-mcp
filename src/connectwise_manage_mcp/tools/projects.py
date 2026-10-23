# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Projects, project tickets and project ticket notes."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api import CWClient
from ..config import Settings
from ._common import (
    CREATE,
    READ,
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
    ref,
    run,
    seg,
)
from .tickets import note_flags, notes_with_children


def register(mcp: FastMCP, settings: Settings) -> None:
    add_search(
        mcp,
        settings,
        name="cw_search_projects",
        description="Search projects in ConnectWise Manage, e.g. conditions company/id = 5 and closedFlag = false.",
        path="/project/projects",
    )
    add_get(
        mcp,
        settings,
        name="cw_get_project",
        description="Get a specific project by ID.",
        path="/project/projects/{id}",
        id_help="Project ID",
    )

    @mcp.tool(
        name="cw_search_project_tickets",
        description=(
            "Search tickets under projects. Use projectId to filter by project, or conditions for CW query syntax."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_search_project_tickets(
        projectId: Annotated[int | None, Field(description="Filter by project ID")] = None,
        conditions: Annotated[str | None, Field(description="ConnectWise conditions query string")] = None,
        page: Page = None,
        pageSize: PageSize = None,
        orderBy: Annotated[str | None, Field(description="Field to order by (e.g. 'id desc')")] = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            cond = join_conditions(f"project/id = {seg(projectId)}" if projectId is not None else None, conditions)
            params = {"conditions": cond, "orderBy": orderBy, "page": number, "pageSize": size}
            rows, has_next = await client.get_page("/project/tickets", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    add_get(
        mcp,
        settings,
        name="cw_get_project_ticket",
        description="Get a specific project ticket by ID.",
        path="/project/tickets/{id}",
        id_help="Project ticket ID",
    )

    @mcp.tool(
        name="cw_get_project_ticket_notes",
        description=(
            "Get notes on a project ticket, oldest first. Page 1 also lists notes of up to 10 child tickets "
            "under child_tickets."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_get_project_ticket_notes(
        id: Annotated[int, Field(description="Project ticket ID")],
        page: Page = None,
        pageSize: PageSize = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            return await notes_with_children(client, "/project/tickets", seg(id), number, size)

        return await run(settings, handler)

    @mcp.tool(
        name="cw_add_project_ticket_note",
        description=(
            "Add a note to a project ticket. Use internalAnalysisFlag for internal-only notes or resolutionFlag for "
            "resolution notes. Defaults to a discussion note. Does not email anyone."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_add_project_ticket_note(
        id: Annotated[int, Field(description="Project ticket ID")],
        text: Annotated[str, Field(description="Note text content")],
        detailDescriptionFlag: Annotated[
            bool | None, Field(description="Discussion note (default when no flag)")
        ] = None,
        internalAnalysisFlag: Annotated[
            bool | None, Field(description="Internal analysis only (default: false)")
        ] = None,
        resolutionFlag: Annotated[bool | None, Field(description="Resolution note (default: false)")] = None,
    ) -> str:
        async def handler(client: CWClient):
            if not text.strip():
                raise ToolInputError("text must not be empty.")
            payload: dict[str, Any] = {
                "text": text,
                **note_flags(detailDescriptionFlag, internalAnalysisFlag, resolutionFlag),
            }
            return clean(await client.post(f"/project/tickets/{seg(id)}/notes", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_create_project",
        description=(
            "Create a new project. ConnectWise usually also needs estimatedStart and estimatedEnd; "
            "managerId is a member ID (cw_search_members)."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_create_project(
        name: Annotated[str, Field(description="Project name")],
        boardId: Annotated[int, Field(description="Project board ID")],
        companyId: Annotated[int, Field(description="Company ID")],
        estimatedStart: Annotated[str | None, Field(description="Estimated start date (ISO 8601)")] = None,
        estimatedEnd: Annotated[str | None, Field(description="Estimated end date (ISO 8601)")] = None,
        description: Annotated[str | None, Field(description="Project description")] = None,
        managerId: Annotated[int | None, Field(description="Project manager member ID")] = None,
    ) -> str:
        async def handler(client: CWClient):
            if not name.strip():
                raise ToolInputError("name must not be empty.")
            payload = body(
                name=name,
                board=ref(boardId),
                company=ref(companyId),
                estimatedStart=estimatedStart,
                estimatedEnd=estimatedEnd,
                description=description,
                manager=ref(managerId),
            )
            return clean(await client.post("/project/projects", payload))

        return await run(settings, handler)
