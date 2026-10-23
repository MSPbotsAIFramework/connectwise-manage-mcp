# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Sales (opportunities, forecasts, stages, sales orders) and procurement (purchase orders, products)."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api import CWClient
from ..config import Settings
from ._common import (
    READ,
    Page,
    PageSize,
    add_get,
    add_search,
    clean,
    join_conditions,
    list_result,
    paging,
    run,
    seg,
)


def register(mcp: FastMCP, settings: Settings) -> None:
    # Opportunities
    add_search(
        mcp,
        settings,
        name="cw_search_opportunities",
        description=('Search sales opportunities, e.g. conditions status/name = "Open" or closedFlag = false.'),
        path="/sales/opportunities",
    )
    add_get(
        mcp,
        settings,
        name="cw_get_opportunity",
        description="Get a specific sales opportunity by ID.",
        path="/sales/opportunities/{id}",
        id_help="Opportunity ID",
    )

    @mcp.tool(
        name="cw_search_opportunity_forecasts",
        description="Get the forecast (revenue items) of a specific opportunity.",
        annotations=READ,
        structured_output=False,
    )
    async def cw_search_opportunity_forecasts(
        opportunityId: Annotated[int, Field(description="Opportunity ID")],
        page: Page = None,
        pageSize: PageSize = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            data = await client.get(f"/sales/opportunities/{seg(opportunityId)}/forecast")
            if isinstance(data, dict) and isinstance(data.get("forecastItems"), list):
                items = data["forecastItems"]
                summary = {k: v for k, v in data.items() if k != "forecastItems"}
            else:
                items = data if isinstance(data, list) else ([data] if data else [])
                summary = {}
            start = (number - 1) * size
            result = list_result(items[start : start + size], number, size, start + size < len(items))
            result["total_count"] = len(items)
            if summary:
                result["forecast"] = clean(summary)
            return result

        return await run(settings, handler)

    @mcp.tool(
        name="cw_search_opportunity_notes",
        description="Get notes on a specific sales opportunity.",
        annotations=READ,
        structured_output=False,
    )
    async def cw_search_opportunity_notes(
        opportunityId: Annotated[int, Field(description="Opportunity ID")],
        page: Page = None,
        pageSize: PageSize = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            params = {"page": number, "pageSize": size}
            rows, has_next = await client.get_page(f"/sales/opportunities/{seg(opportunityId)}/notes", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    add_search(
        mcp,
        settings,
        name="cw_search_sales_stages",
        description="List sales pipeline stages in ConnectWise Manage.",
        path="/sales/stages",
    )

    # Purchase orders
    add_search(
        mcp,
        settings,
        name="cw_search_purchase_orders",
        description=(
            "Search purchase orders (the buy side), e.g. conditions closedFlag = false, "
            'vendorCompany/name = "Vendor", poDate > [2026-01-01T00:00:00Z].'
        ),
        path="/procurement/purchaseorders",
        order_help="Field to order by (e.g. 'poDate desc')",
    )
    add_get(
        mcp,
        settings,
        name="cw_get_purchase_order",
        description="Get a specific purchase order by ID.",
        path="/procurement/purchaseorders/{id}",
        id_help="Purchase order ID",
    )

    @mcp.tool(
        name="cw_get_purchase_order_items",
        description=(
            "Get the line items of a purchase order, with unit cost, extended cost, quantity received "
            "and receipt status."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_get_purchase_order_items(
        purchaseOrderId: Annotated[int, Field(description="Purchase order ID")],
        conditions: Annotated[str | None, Field(description="ConnectWise conditions query string")] = None,
        page: Page = None,
        pageSize: PageSize = None,
        orderBy: Annotated[str | None, Field(description="Field to order by")] = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            params = {"conditions": join_conditions(conditions), "orderBy": orderBy, "page": number, "pageSize": size}
            rows, has_next = await client.get_page(
                f"/procurement/purchaseorders/{seg(purchaseOrderId)}/lineitems", params
            )
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    # Procurement products
    add_search(
        mcp,
        settings,
        name="cw_search_procurement_products",
        description=(
            "Search procurement product items: catalog SKUs placed on a ticket, project, sales order or opportunity, "
            "with their own price, cost and margin (for catalog definitions use cw_search_catalog_items). "
            "E.g. conditions company/id = 42 or invoice/id = 1001."
        ),
        path="/procurement/products",
    )
    add_get(
        mcp,
        settings,
        name="cw_get_procurement_product",
        description="Get a specific procurement product item by ID.",
        path="/procurement/products/{id}",
        id_help="Procurement product item ID",
    )

    # Sales orders
    add_search(
        mcp,
        settings,
        name="cw_search_sales_orders",
        description=(
            'Search sales orders (the sell side), e.g. conditions status/name = "Open" or company/name = "Acme". '
            "For purchase orders use cw_search_purchase_orders."
        ),
        path="/sales/orders",
    )
    add_get(
        mcp,
        settings,
        name="cw_get_sales_order",
        description="Get a specific sales order by ID.",
        path="/sales/orders/{id}",
        id_help="Sales order ID",
    )

    @mcp.tool(
        name="cw_get_sales_order_products",
        description=(
            "Get the procurement product items on a sales order. Extra conditions are ANDed with the order filter."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_get_sales_order_products(
        salesOrderId: Annotated[int, Field(description="Sales order ID")],
        conditions: Annotated[
            str | None, Field(description="Additional ConnectWise conditions, ANDed with the sales order filter")
        ] = None,
        page: Page = None,
        pageSize: PageSize = None,
        orderBy: Annotated[str | None, Field(description="Field to order by")] = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            cond = join_conditions(f"salesOrder/id = {seg(salesOrderId)}", conditions)
            params = {"conditions": cond, "orderBy": orderBy, "page": number, "pageSize": size}
            rows, has_next = await client.get_page("/procurement/products", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)
