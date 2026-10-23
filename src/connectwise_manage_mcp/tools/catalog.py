# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Product catalog: items, categories, subcategories and manufacturers."""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api import CWClient
from ..config import Settings
from ._common import (
    CREATE,
    UPDATE,
    Operations,
    ToolInputError,
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
        name="cw_search_catalog_items",
        description=(
            'Search the product catalog. Use conditions for CW query syntax, e.g. identifier like "%SKU-%" or '
            "manufacturer/id = 5."
        ),
        path="/procurement/catalog",
        order_help="Field to order by (e.g. 'identifier asc')",
    )
    add_get(
        mcp,
        settings,
        name="cw_get_catalog_item",
        description="Get a specific catalog item by ID.",
        path="/procurement/catalog/{id}",
        id_help="Catalog item ID",
    )

    @mcp.tool(
        name="cw_create_catalog_item",
        description=(
            "Create a catalog item (product SKU). Common fields are parameters; put any other catalog field "
            "(e.g. manufacturerPartNumber, unitOfMeasure, minStockLevel) in extraFields. Unknown fields are "
            "silently dropped by ConnectWise."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_create_catalog_item(
        identifier: Annotated[str, Field(description="Unique catalog item identifier / SKU")],
        description: Annotated[str, Field(description="Product description")],
        subcategoryId: Annotated[int, Field(description="Catalog subcategory ID (required by CW)")],
        typeId: Annotated[int, Field(description="Product type ID (required by CW)")],
        cost: Annotated[float | None, Field(description="Cost to you")] = None,
        price: Annotated[float | None, Field(description="Sale price")] = None,
        categoryId: Annotated[int | None, Field(description="Catalog category ID")] = None,
        manufacturerId: Annotated[int | None, Field(description="Manufacturer ID")] = None,
        productClass: Annotated[
            Literal["NonInventory", "Inventory", "Bundle", "Service", "Agreement"] | None,
            Field(description="Product class"),
        ] = None,
        taxableFlag: Annotated[bool | None, Field(description="Whether the item is taxable")] = None,
        customerDescription: Annotated[str | None, Field(description="Customer-facing description")] = None,
        extraFields: Annotated[
            dict[str, Any] | None,
            Field(
                description="Additional catalog item fields, merged into the request body (explicit parameters win)."
            ),
        ] = None,
    ) -> str:
        async def handler(client: CWClient):
            if not identifier.strip() or not description.strip():
                raise ToolInputError("identifier and description must not be empty.")
            payload: dict[str, Any] = dict(extraFields or {})
            payload.update(
                body(
                    identifier=identifier,
                    description=description,
                    subcategory=ref(subcategoryId),
                    type=ref(typeId),
                    cost=cost,
                    price=price,
                    category=ref(categoryId),
                    manufacturer=ref(manufacturerId),
                    productClass=productClass,
                    taxableFlag=taxableFlag,
                    customerDescription=customerDescription,
                )
            )
            return clean(await client.post("/procurement/catalog", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_update_catalog_item",
        description="Update a catalog item using JSON Patch operations (paths such as 'price', 'cost', 'description').",
        annotations=UPDATE,
        structured_output=False,
    )
    async def cw_update_catalog_item(
        id: Annotated[int, Field(description="Catalog item ID")],
        operations: Operations,
    ) -> str:
        async def handler(client: CWClient):
            ops, replace_only = patch_ops(operations)
            return clean(await client.patch(f"/procurement/catalog/{seg(id)}", ops, idempotent=replace_only))

        return await run(settings, handler)

    add_search(
        mcp,
        settings,
        name="cw_list_catalog_categories",
        description="List product categories from the ConnectWise catalog.",
        path="/procurement/categories",
    )
    add_search(
        mcp,
        settings,
        name="cw_list_catalog_subcategories",
        description="List product subcategories from the ConnectWise catalog.",
        path="/procurement/subcategories",
        conditions_help="ConnectWise conditions query string (e.g. category/id = 3)",
    )
    add_search(
        mcp,
        settings,
        name="cw_list_manufacturers",
        description="List manufacturers referenced by catalog items.",
        path="/procurement/manufacturers",
    )
