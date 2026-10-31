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

    @mcp.tool(
        name="cw_update_configuration",
        description=(
            "Update an existing configuration item (asset/CI) using JSON Patch operations (paths such as "
            "'name', 'status/id', 'activeFlag', 'ram', 'ipAddress')."
        ),
        annotations=UPDATE,
        structured_output=False,
    )
    async def cw_update_configuration(
        id: Annotated[int, Field(description="Configuration item ID")],
        operations: Operations,
    ) -> str:
        async def handler(client: CWClient):
            ops, replace_only = patch_ops(operations)
            return clean(await client.patch(f"/company/configurations/{seg(id)}", ops, idempotent=replace_only))

        return await run(settings, handler)

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

    # Ticket classification (type / subtype / item are configured per service board)
    @mcp.tool(
        name="cw_list_ticket_types",
        description=(
            "List ticket types configured on a service board. Use the IDs as typeId when creating or "
            "updating tickets on that board."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_list_ticket_types(
        boardId: Annotated[int, Field(description="Service board ID")],
        conditions: Annotated[str | None, Field(description="ConnectWise conditions query string")] = None,
        page: Page = None,
        pageSize: PageSize = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            params = {"conditions": join_conditions(conditions), "page": number, "pageSize": size}
            rows, has_next = await client.get_page(f"/service/boards/{seg(boardId)}/types", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    @mcp.tool(
        name="cw_list_ticket_subtypes",
        description=(
            "List ticket subtypes on a service board. Pass typeId to get only the subtypes allowed for that "
            "ticket type (from the board's type/subtype/item associations)."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_list_ticket_subtypes(
        boardId: Annotated[int, Field(description="Service board ID")],
        typeId: Annotated[int | None, Field(description="Only subtypes associated with this ticket type")] = None,
        conditions: Annotated[str | None, Field(description="ConnectWise conditions query string")] = None,
        page: Page = None,
        pageSize: PageSize = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            if typeId is not None:
                return await _associated(client, boardId, "subType", typeId=typeId)
            params = {"conditions": join_conditions(conditions), "page": number, "pageSize": size}
            rows, has_next = await client.get_page(f"/service/boards/{seg(boardId)}/subtypes", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    @mcp.tool(
        name="cw_list_ticket_items",
        description=(
            "List ticket items on a service board. Pass typeId and/or subTypeId to get only the items allowed "
            "for that type and subtype (from the board's type/subtype/item associations)."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_list_ticket_items(
        boardId: Annotated[int, Field(description="Service board ID")],
        typeId: Annotated[int | None, Field(description="Only items associated with this ticket type")] = None,
        subTypeId: Annotated[int | None, Field(description="Only items associated with this subtype")] = None,
        conditions: Annotated[str | None, Field(description="ConnectWise conditions query string")] = None,
        page: Page = None,
        pageSize: PageSize = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            if typeId is not None or subTypeId is not None:
                return await _associated(client, boardId, "item", typeId=typeId, subTypeId=subTypeId)
            params = {"conditions": join_conditions(conditions), "page": number, "pageSize": size}
            rows, has_next = await client.get_page(f"/service/boards/{seg(boardId)}/items", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    # Time entry setup
    add_search(
        mcp,
        settings,
        name="cw_list_work_types",
        description="List work types (workTypeId on time entries) in ConnectWise Manage.",
        path="/time/workTypes",
    )
    add_search(
        mcp,
        settings,
        name="cw_list_work_roles",
        description="List work roles (workRoleId on time entries) in ConnectWise Manage.",
        path="/time/workRoles",
    )

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


async def _associated(
    client: CWClient, board_id: int, field: str, *, typeId: int | None = None, subTypeId: int | None = None
) -> dict:
    """Distinct subtypes or items allowed on a board for a type / subtype, read from its associations."""
    conditions = join_conditions(
        f"type/id = {int(typeId)}" if typeId is not None else None,
        f"subType/id = {int(subTypeId)}" if subTypeId is not None else None,
    )
    rows = await client.get_all(
        f"/service/boards/{seg(board_id)}/typeSubTypeItemAssociations", {"conditions": conditions}
    )
    seen: dict[int, dict] = {}
    for row in rows:
        value = row.get(field) if isinstance(row, dict) else None
        if isinstance(value, dict) and value.get("id") is not None:
            seen.setdefault(value["id"], {"id": value["id"], "name": value.get("name")})
    items = sorted(seen.values(), key=lambda v: str(v.get("name") or ""))
    return {"items": items, "count": len(items), "source": "typeSubTypeItemAssociations", "has_more": False}
