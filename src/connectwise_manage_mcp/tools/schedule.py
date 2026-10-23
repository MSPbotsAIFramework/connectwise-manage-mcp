# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Schedule entries (booked resource time), schedule types and statuses."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api import CWClient
from ..config import Settings
from ._common import CREATE, DESTRUCTIVE, Operations, add_search, body, clean, patch_ops, ref, run, seg

UTC_NOTE = "ConnectWise reads dateStart and dateEnd as UTC (trailing 'Z'); convert local times first."


def register(mcp: FastMCP, settings: Settings) -> None:
    add_search(
        mcp,
        settings,
        name="cw_search_schedule_entries",
        description=(
            "Search schedule entries (booked resource time). Each entry has objectId (the ticket, activity or "
            "project ticket it is booked against), member, dateStart, dateEnd, type, status, doneFlag and hours. "
            + UTC_NOTE
        ),
        path="/schedule/entries",
        conditions_help=(
            "ConnectWise conditions, e.g. member/id = 147 and dateStart >= [2026-09-22T00:00:00Z]. "
            "Date literals go in square brackets and are UTC."
        ),
        order_help="Field to order by (e.g. 'dateStart asc')",
    )
    add_search(
        mcp,
        settings,
        name="cw_list_schedule_types",
        description=(
            "List schedule types. The type decides what an entry books against: typically 'S' Service "
            "(service ticket), 'P' Project, 'C' Sales (activity), 'N' Meeting. Call before creating an entry."
        ),
        path="/schedule/types",
    )
    add_search(
        mcp,
        settings,
        name="cw_list_schedule_statuses",
        description="List schedule statuses (usually Tentative and Firm; one is flagged as the default).",
        path="/schedule/statuses",
    )

    @mcp.tool(
        name="cw_create_schedule_entry",
        description=(
            "Book resource time by creating a schedule entry against a ticket, activity or project ticket (a forward "
            "booking; record work done with cw_create_time_entry). memberId is never assumed: confirm who the "
            "booking is for. " + UTC_NOTE
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_create_schedule_entry(
        objectId: Annotated[
            int,
            Field(description="Service ticket ID (Service type), project ticket ID (Project) or activity ID (Sales)"),
        ],
        typeId: Annotated[int, Field(description="Schedule type ID from cw_list_schedule_types")],
        memberId: Annotated[int, Field(description="Member ID the time is booked for; confirm before booking")],
        dateStart: Annotated[str, Field(description="Start in UTC ISO 8601, e.g. '2026-09-22T02:00:00Z'")],
        dateEnd: Annotated[str, Field(description="End in UTC ISO 8601, e.g. '2026-09-22T03:00:00Z'")],
        statusId: Annotated[
            int | None,
            Field(description="Schedule status ID (cw_list_schedule_statuses); defaults to the instance default"),
        ] = None,
        reminderId: Annotated[
            int | None, Field(description="Reminder lead time ID, as carried on existing entries")
        ] = None,
        whereId: Annotated[int | None, Field(description="Service location ID (e.g. On-Site, Remote)")] = None,
        spanId: Annotated[int | None, Field(description="Schedule span ID")] = None,
        name: Annotated[
            str | None, Field(description="Entry name; generated from the linked object when omitted")
        ] = None,
        hours: Annotated[float | None, Field(description="Booked hours; derived from the dates when omitted")] = None,
        doneFlag: Annotated[bool | None, Field(description="Mark the booking as done (default: false)")] = None,
        ownerFlag: Annotated[bool | None, Field(description="Mark the member as the owner of the entry")] = None,
        acknowledgedFlag: Annotated[bool | None, Field(description="Mark the entry as acknowledged")] = None,
        allowScheduleConflictsFlag: Annotated[
            bool | None, Field(description="Allow overlapping an existing entry for the member (default: false)")
        ] = None,
    ) -> str:
        async def handler(client: CWClient):
            payload = body(
                objectId=int(seg(objectId)),
                type=ref(typeId),
                member=ref(memberId),
                dateStart=dateStart,
                dateEnd=dateEnd,
                status=ref(statusId),
                reminder=ref(reminderId),
                where=ref(whereId),
                span=ref(spanId),
                name=name,
                hours=hours,
                doneFlag=doneFlag,
                ownerFlag=ownerFlag,
                acknowledgedFlag=acknowledgedFlag,
                allowScheduleConflictsFlag=allowScheduleConflictsFlag,
            )
            return clean(await client.post("/schedule/entries", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_update_schedule_entry",
        description=(
            "Update a schedule entry with JSON Patch, e.g. to move a booking (dateStart, dateEnd), change status/id "
            "or member/id, or set doneFlag. There is no delete tool. " + UTC_NOTE
        ),
        annotations=DESTRUCTIVE,
        structured_output=False,
    )
    async def cw_update_schedule_entry(
        id: Annotated[int, Field(description="Schedule entry ID")],
        operations: Operations,
    ) -> str:
        async def handler(client: CWClient):
            ops, replace_only = patch_ops(operations)
            return clean(await client.patch(f"/schedule/entries/{seg(id)}", ops, idempotent=replace_only))

        return await run(settings, handler)
