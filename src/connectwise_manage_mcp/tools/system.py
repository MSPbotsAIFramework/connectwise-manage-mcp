# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Members, configurations, service board setup, activities and the connectivity check."""

from typing import Annotated

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

SYSTEM_INFO_FIELDS = ("version", "isCloud", "serverTimeZone", "licenseBits", "cloudRegion")


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="cw_test_connection",
        description=(
            "Test the connection to ConnectWise Manage by fetching system info. Returns API version "
            "and licensing details."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_test_connection() -> str:
        async def handler(client: CWClient):
            info = await client.get("/system/info") or {}
            details = {k: info[k] for k in SYSTEM_INFO_FIELDS if k in info}
            return {
                "status": "ok",
                "message": "ConnectWise Manage is reachable and the credentials were accepted.",
                **details,
            }

        return await run(settings, handler)

    # Members
    add_search(
        mcp,
        settings,
        name="cw_search_members",
        description="Search members (technicians/users) in ConnectWise Manage.",
        path="/system/members",
        conditions_help='ConnectWise conditions query string (e.g. identifier = "jsmith")',
    )
    add_get(
        mcp,
        settings,
        name="cw_get_member",
        description="Get a specific member by ID.",
        path="/system/members/{id}",
        id_help="Member ID",
    )

    # Configurations
    add_search(
        mcp,
        settings,
        name="cw_search_configurations",
        description="Search configuration items (assets/CIs) in ConnectWise Manage.",
        path="/company/configurations",
        conditions_help='ConnectWise conditions query string (e.g. company/name = "Acme")',
    )
    add_get(
        mcp,
        settings,
        name="cw_get_configuration",
        description="Get a specific configuration item (asset/CI) by ID.",
        path="/company/configurations/{id}",
        id_help="Configuration item ID",
    )

    # Service board setup
    add_search(
        mcp,
        settings,
        name="cw_list_boards",
        description="List service boards in ConnectWise Manage.",
        path="/service/boards",
    )
    add_search(
        mcp,
        settings,
        name="cw_list_priorities",
        description="List ticket priorities in ConnectWise Manage.",
        path="/service/priorities",
    )

    @mcp.tool(
        name="cw_list_statuses",
        description="List ticket statuses for a specific service board in ConnectWise Manage.",
        annotations=READ,
        structured_output=False,
    )
    async def cw_list_statuses(
        boardId: Annotated[int, Field(description="Service board ID")],
        conditions: Annotated[str | None, Field(description="ConnectWise conditions query string")] = None,
        page: Page = None,
        pageSize: PageSize = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            params = {"conditions": join_conditions(conditions), "page": number, "pageSize": size}
            rows, has_next = await client.get_page(f"/service/boards/{seg(boardId)}/statuses", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    # Activities
    add_search(
        mcp,
        settings,
        name="cw_search_activities",
        description="Search sales activities (calls, meetings, follow-ups) in ConnectWise Manage.",
        path="/sales/activities",
    )
    add_get(
        mcp,
        settings,
        name="cw_get_activity",
        description="Get a specific activity by ID.",
        path="/sales/activities/{id}",
        id_help="Activity ID",
    )

    @mcp.tool(
        name="cw_create_activity",
        description="Create a new sales activity. memberId is the member the activity is assigned to.",
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_create_activity(
        name: Annotated[str, Field(description="Activity name/subject")],
        typeId: Annotated[int | None, Field(description="Activity type ID")] = None,
        companyId: Annotated[int | None, Field(description="Company ID")] = None,
        contactId: Annotated[int | None, Field(description="Contact ID")] = None,
        memberId: Annotated[int | None, Field(description="Assigned member ID")] = None,
        notes: Annotated[str | None, Field(description="Activity notes")] = None,
        dateStart: Annotated[str | None, Field(description="Start date (ISO 8601, UTC)")] = None,
        dateEnd: Annotated[str | None, Field(description="End date (ISO 8601, UTC)")] = None,
    ) -> str:
        async def handler(client: CWClient):
            if not name.strip():
                raise ToolInputError("name must not be empty.")
            payload = body(
                name=name,
                type=ref(typeId),
                company=ref(companyId),
                contact=ref(contactId),
                assignTo=ref(memberId),
                notes=notes,
                dateStart=dateStart,
                dateEnd=dateEnd,
            )
            return clean(await client.post("/sales/activities", payload))

        return await run(settings, handler)
