# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Companies (MSP clients, vendors, prospects) and their sites."""

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
    ToolInputError,
    add_get,
    add_search,
    body,
    clean,
    join_conditions,
    list_result,
    page_size_param,
    paging,
    patch_ops,
    ref,
    run,
    seg,
)


def register(mcp: FastMCP, settings: Settings) -> None:
    add_search(
        mcp,
        settings,
        name="cw_search_companies",
        description=(
            "Search companies in ConnectWise Manage. Use 'conditions' for CW query syntax, "
            'e.g. name like "%Acme%" or identifier = "AcmeCorp".'
        ),
        path="/company/companies",
        order_help="Field to order by (e.g. 'name asc')",
    )
    add_get(
        mcp,
        settings,
        name="cw_get_company",
        description="Get a specific company by ID.",
        path="/company/companies/{id}",
        id_help="Company ID",
    )

    @mcp.tool(
        name="cw_list_sites",
        description=(
            "List a company's sites (locations) with their IDs and addresses, e.g. to pick the site for a new contact."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_list_sites(
        companyId: Annotated[int, Field(description="Company ID")],
        conditions: Annotated[
            str | None, Field(description='Optional ConnectWise conditions, e.g. name like "%Main%"')
        ] = None,
        pageSize: page_size_param(50) = None,
        page: Page = None,
    ) -> str:
        number, size = paging(page, pageSize, default=50)

        async def handler(client: CWClient):
            params = {"conditions": join_conditions(conditions), "page": number, "pageSize": size}
            rows, has_next = await client.get_page(f"/company/companies/{seg(companyId)}/sites", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    @mcp.tool(
        name="cw_create_company",
        description=(
            'Create a new company. ConnectWise requires a primary site; siteName defaults to "Main". '
            "Address fields are stored on the company and its primary site."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_create_company(
        name: Annotated[str, Field(description="Company name")],
        identifier: Annotated[str, Field(description="Unique company identifier (short code, max 25 characters)")],
        typeIds: Annotated[list[int] | None, Field(description="Array of company type IDs")] = None,
        statusId: Annotated[int | None, Field(description="Company status ID")] = None,
        addressLine1: Annotated[str | None, Field(description="Street address")] = None,
        city: Annotated[str | None, Field(description="City")] = None,
        state: Annotated[str | None, Field(description="State/province")] = None,
        zip: Annotated[str | None, Field(description="Postal/ZIP code")] = None,
        country: Annotated[str | None, Field(description="Country name, or country ID as digits")] = None,
        phoneNumber: Annotated[str | None, Field(description="Phone number")] = None,
        website: Annotated[str | None, Field(description="Website URL")] = None,
        siteName: Annotated[str | None, Field(description='Name of the primary site (default: "Main")')] = None,
    ) -> str:
        async def handler(client: CWClient):
            if not name.strip() or not identifier.strip():
                raise ToolInputError("name and identifier must not be empty.")
            country_ref = None
            if country and country.strip():
                text = country.strip()
                country_ref = {"id": int(text)} if text.isdigit() else {"name": text}
            payload = body(
                name=name,
                identifier=identifier,
                site={"name": (siteName or "").strip() or "Main"},
                types=[ref(t) for t in typeIds] if typeIds else None,
                status=ref(statusId),
                addressLine1=addressLine1,
                city=city,
                state=state,
                zip=zip,
                country=country_ref,
                phoneNumber=phoneNumber,
                website=website,
            )
            return clean(await client.post("/company/companies", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_update_company",
        description=(
            "Update an existing company using JSON Patch operations (paths such as 'name', 'phoneNumber', 'status/id')."
        ),
        annotations=UPDATE,
        structured_output=False,
    )
    async def cw_update_company(
        id: Annotated[int, Field(description="Company ID")],
        operations: Operations,
    ) -> str:
        async def handler(client: CWClient):
            ops, replace_only = patch_ops(operations)
            return clean(await client.patch(f"/company/companies/{seg(id)}", ops, idempotent=replace_only))

        return await run(settings, handler)
