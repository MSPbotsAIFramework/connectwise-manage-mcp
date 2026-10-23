# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Time entries (work done)."""

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api import CWClient
from ..config import Settings
from ._common import (
    CREATE,
    DESTRUCTIVE,
    UPDATE,
    Operations,
    add_get,
    add_search,
    body,
    clean,
    patch_ops,
    ref,
    run,
    seg,
)


def register(mcp: FastMCP, settings: Settings) -> None:
    add_search(
        mcp,
        settings,
        name="cw_search_time_entries",
        description="Search time entries in ConnectWise Manage.",
        path="/time/entries",
        conditions_help='ConnectWise conditions query string (e.g. member/identifier = "jsmith")',
    )
    add_get(
        mcp,
        settings,
        name="cw_get_time_entry",
        description="Get a specific time entry by ID.",
        path="/time/entries/{id}",
        id_help="Time entry ID",
    )

    @mcp.tool(
        name="cw_create_time_entry",
        description=(
            "Create a time entry (work done) against a service ticket, project ticket, charge code or activity. "
            "Give timeEnd or actualHours."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_create_time_entry(
        chargeToType: Annotated[
            Literal["ServiceTicket", "ProjectTicket", "ChargeCode", "Activity"],
            Field(description="What to charge the time to"),
        ],
        chargeToId: Annotated[int, Field(description="ID of the ticket, charge code, or activity")],
        memberId: Annotated[int, Field(description="Member ID for the time entry")],
        timeStart: Annotated[str, Field(description="Start time (ISO 8601, UTC)")],
        timeEnd: Annotated[str | None, Field(description="End time (ISO 8601, UTC)")] = None,
        actualHours: Annotated[float | None, Field(description="Actual hours worked (alternative to timeEnd)")] = None,
        notes: Annotated[str | None, Field(description="Work notes")] = None,
        internalNotes: Annotated[str | None, Field(description="Internal-only notes")] = None,
        workTypeId: Annotated[int | None, Field(description="Work type ID")] = None,
        workRoleId: Annotated[int | None, Field(description="Work role ID")] = None,
    ) -> str:
        async def handler(client: CWClient):
            payload = body(
                chargeToType=chargeToType,
                chargeToId=int(seg(chargeToId)),
                member=ref(memberId),
                timeStart=timeStart,
                timeEnd=timeEnd,
                actualHours=actualHours,
                notes=notes,
                internalNotes=internalNotes,
                workType=ref(workTypeId),
                workRole=ref(workRoleId),
            )
            return clean(await client.post("/time/entries", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_update_time_entry",
        description=(
            "Correct a time entry with JSON Patch. Paths are field names such as actualHours, notes, internalNotes, "
            "timeStart, timeEnd or billableOption. Hours on metered agreements round to 0.25; billed entries may "
            "be rejected."
        ),
        annotations=UPDATE,
        structured_output=False,
    )
    async def cw_update_time_entry(
        id: Annotated[int, Field(description="Time entry ID")],
        operations: Operations,
    ) -> str:
        async def handler(client: CWClient):
            ops, replace_only = patch_ops(operations)
            return clean(await client.patch(f"/time/entries/{seg(id)}", ops, idempotent=replace_only))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_delete_time_entry",
        description=(
            "Delete a time entry, e.g. a mistaken one before it is billed. ConnectWise rejects deletes "
            "of billed entries."
        ),
        annotations=DESTRUCTIVE,
        structured_output=False,
    )
    async def cw_delete_time_entry(id: Annotated[int, Field(description="Time entry ID")]) -> str:
        async def handler(client: CWClient):
            await client.delete(f"/time/entries/{seg(id)}")
            return {"deleted": True, "id": int(seg(id))}

        return await run(settings, handler)
