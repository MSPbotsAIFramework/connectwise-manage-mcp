# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Inventory: warehouses, bins, on-hand stock and inventory adjustments."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api import CWClient
from ..config import Settings
from ._common import (
    CREATE,
    DESTRUCTIVE,
    READ,
    Page,
    PageSize,
    ToolInputError,
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

MAX_BINS = 200
MIN_TIME_LEFT = 10.0
SERIAL_MAX = 1000


def _ref_id(value: Any) -> Any:
    return value.get("id") if isinstance(value, dict) else None


def _on_hand(row: dict[str, Any]) -> float:
    for key in ("onHand", "quantityOnHand", "quantity"):
        if isinstance(row.get(key), int | float):
            return row[key]
    return 0


def register(mcp: FastMCP, settings: Settings) -> None:
    add_search(
        mcp,
        settings,
        name="cw_list_warehouses",
        description=(
            "List inventory warehouses. A warehouse groups the bins that hold stock; start here before reading "
            "on-hand quantities or building an adjustment. A locked warehouse (lockedFlag) rejects adjustments."
        ),
        path="/procurement/warehouses",
        conditions_help='ConnectWise conditions query string (e.g. inactiveFlag = false or name like "%Main%")',
        order_help="Field to order by (e.g. 'name asc')",
    )

    @mcp.tool(
        name="cw_list_warehouse_bins",
        description=(
            "List warehouse bins (where stock sits; every adjustment line names one). Pass warehouseId to list one "
            "warehouse's bins. A bin's quantityOnHand is a rollup; use cw_get_inventory_on_hand for per-item stock."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_list_warehouse_bins(
        warehouseId: Annotated[int | None, Field(description="Only return bins belonging to this warehouse ID")] = None,
        conditions: Annotated[
            str | None, Field(description="ConnectWise conditions (e.g. inactiveFlag = false); ANDed with warehouseId")
        ] = None,
        page: Page = None,
        pageSize: PageSize = None,
        orderBy: Annotated[str | None, Field(description="Field to order by (e.g. 'name asc')")] = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            cond = join_conditions(
                f"warehouse/id = {seg(warehouseId)}" if warehouseId is not None else None, conditions
            )
            params = {"conditions": cond, "orderBy": orderBy, "page": number, "pageSize": size}
            rows, has_next = await client.get_page("/procurement/warehouseBins", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    @mcp.tool(
        name="cw_get_inventory_on_hand",
        description=(
            "Report catalog items with non-zero (including negative) stock, one row per warehouse bin, with "
            "quantity, unit cost and extended value. ConnectWise exposes on-hand only per bin, so this walks bins "
            "(at most 200 per call): pass warehouseId or binIds. unitCost is the catalog item's cost, not the "
            "weighted average cost."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_get_inventory_on_hand(
        warehouseId: Annotated[
            int | None, Field(description="Only scan bins in this warehouse ID (recommended)")
        ] = None,
        binIds: Annotated[
            list[int] | None, Field(description="Only scan these warehouse bin IDs; takes precedence over warehouseId")
        ] = None,
        catalogItemId: Annotated[int | None, Field(description="Only report rows for this catalog item ID")] = None,
        includeInactiveBins: Annotated[
            bool | None, Field(description="Include bins flagged inactive (default: false)")
        ] = None,
        includeSerialNumbers: Annotated[
            bool | None, Field(description="Include serial numbers when ConnectWise returns them (default: true)")
        ] = None,
        includeCosts: Annotated[
            bool | None, Field(description="Look up catalog cost and description for extended value (default: true)")
        ] = None,
    ) -> str:
        async def handler(client: CWClient):
            if binIds:
                ids = [int(seg(b)) for b in binIds]
                bins = [{"id": b} for b in dict.fromkeys(ids)]
            else:
                cond = join_conditions(
                    f"warehouse/id = {seg(warehouseId)}" if warehouseId is not None else None,
                    None if includeInactiveBins else "inactiveFlag = false",
                )
                bins = await client.get_all(
                    "/procurement/warehouseBins", {"conditions": cond}, page_size=MAX_BINS, max_rows=MAX_BINS + 1
                )
            truncated = len(bins) > MAX_BINS
            bins = bins[:MAX_BINS]

            rows: list[dict[str, Any]] = []
            scanned = 0
            for b in bins:
                if client.time_left() < min(MIN_TIME_LEFT, settings.call_budget_seconds / 5):
                    truncated = True
                    break
                bin_id = seg(b.get("id"))
                items = await client.get_all(f"/procurement/warehouseBins/{bin_id}/inventoryOnHand", max_rows=5000)
                scanned += 1
                for item in items:
                    qty = _on_hand(item)
                    item_id = _ref_id(item.get("catalogItem"))
                    if not qty or (catalogItemId is not None and item_id != catalogItemId):
                        continue
                    row = {
                        "catalogItemId": item_id,
                        "identifier": (item.get("catalogItem") or {}).get("identifier"),
                        "description": item.get("description"),
                        "warehouse": clean(item.get("warehouse") or b.get("warehouse")),
                        "warehouseBin": clean(item.get("warehouseBin") or {"id": int(bin_id), "name": b.get("name")}),
                        "onHand": qty,
                    }
                    serials = item.get("serialNumbers") or item.get("serialNumber")
                    if includeSerialNumbers is not False and serials:
                        row["serialNumbers"] = serials
                    rows.append(row)

            if includeCosts is not False and rows:
                ids = sorted({r["catalogItemId"] for r in rows if isinstance(r["catalogItemId"], int)})
                costs: dict[int, dict[str, Any]] = {}
                for start in range(0, len(ids), 50):
                    chunk = ids[start : start + 50]
                    found = await client.get_all(
                        "/procurement/catalog",
                        {
                            "conditions": f"id in ({','.join(str(i) for i in chunk)})",
                            "fields": "id,identifier,description,cost",
                        },
                        page_size=50,
                        max_rows=50,
                    )
                    costs.update({c["id"]: c for c in found if "id" in c})
                for r in rows:
                    c = costs.get(r["catalogItemId"]) or {}
                    r["identifier"] = r["identifier"] or c.get("identifier")
                    r["description"] = r["description"] or c.get("description")
                    if isinstance(c.get("cost"), int | float):
                        r["unitCost"] = c["cost"]
                        r["extendedValue"] = round(c["cost"] * r["onHand"], 4)

            result: dict[str, Any] = {"items": rows, "count": len(rows), "bins_scanned": scanned, "has_more": truncated}
            if truncated:
                result["note"] = "Not every bin was scanned. Narrow with warehouseId or binIds."
            return result

        return await run(settings, handler)

    add_search(
        mcp,
        settings,
        name="cw_list_adjustment_types",
        description=(
            "List inventory adjustment types (identifier, name, auditTrailFlag). Every adjustment needs one, and "
            "the type decides the general ledger account, so choose deliberately."
        ),
        path="/procurement/adjustments/types",
        order_help="Field to order by (e.g. 'identifier asc')",
    )

    @mcp.tool(
        name="cw_create_adjustment",
        description=(
            "Create an inventory adjustment header and return its ID. Moves no stock: add lines with "
            "cw_add_adjustment_detail, then post with cw_close_adjustment only if the user intends to. There is no "
            "delete tool. Free text goes in reason (max 100, shown in lists) and notes."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_create_adjustment(
        identifier: Annotated[
            str, Field(description="Adjustment identifier, unique (max 50 characters)", max_length=50)
        ],
        typeId: Annotated[int, Field(description="Adjustment type ID from cw_list_adjustment_types")],
        reason: Annotated[str | None, Field(description="Short reason (max 100 characters)", max_length=100)] = None,
        notes: Annotated[str | None, Field(description="Free-text notes for the fuller explanation")] = None,
    ) -> str:
        async def handler(client: CWClient):
            if not identifier.strip():
                raise ToolInputError("identifier must not be empty.")
            payload = body(identifier=identifier, type=ref(typeId), reason=reason, notes=notes)
            return clean(await client.post("/procurement/adjustments", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_add_adjustment_detail",
        description=(
            "Add one line to an open adjustment. quantityAdjusted is a signed whole-unit change (-7 zeroes a bin "
            "holding 7). warehouseId and warehouseBinId are both required. Pass serialNumbers for serialised items. "
            "Leave unitCost unset to let ConnectWise apply its average cost. Nothing posts until cw_close_adjustment."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_add_adjustment_detail(
        adjustmentId: Annotated[int, Field(description="Adjustment header ID from cw_create_adjustment")],
        catalogItemId: Annotated[int, Field(description="Catalog item ID being adjusted")],
        warehouseId: Annotated[int, Field(description="Warehouse ID holding the stock")],
        warehouseBinId: Annotated[int, Field(description="Warehouse bin ID holding the stock")],
        quantityAdjusted: Annotated[
            int, Field(description="Signed whole-unit change to on-hand; negative removes stock")
        ],
        unitCost: Annotated[
            float | None, Field(description="Unit cost; omit to use ConnectWise's average cost")
        ] = None,
        description: Annotated[
            str | None, Field(description="Line description (max 50 characters)", max_length=50)
        ] = None,
        serialNumbers: Annotated[
            list[str] | None,
            Field(description="Serial numbers being adjusted; joined with commas (max 1000 characters)"),
        ] = None,
    ) -> str:
        async def handler(client: CWClient):
            if quantityAdjusted == 0:
                raise ToolInputError("quantityAdjusted must not be 0.")
            serial = None
            if serialNumbers:
                serial = ",".join(s.strip() for s in serialNumbers if s and s.strip())
                if len(serial) > SERIAL_MAX:
                    raise ToolInputError(f"serialNumbers joined exceed {SERIAL_MAX} characters.")
            payload = body(
                catalogItem=ref(catalogItemId),
                warehouse=ref(warehouseId),
                warehouseBin=ref(warehouseBinId),
                quantityAdjusted=quantityAdjusted,
                unitCost=unitCost,
                description=description,
                serialNumber=serial or None,
            )
            return clean(await client.post(f"/procurement/adjustments/{seg(adjustmentId)}/details", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_get_adjustment",
        description=(
            "Get an inventory adjustment header with all its detail lines, e.g. to check it before "
            "cw_close_adjustment. closedFlag shows whether it has already posted."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_get_adjustment(id: Annotated[int, Field(description="Adjustment ID")]) -> str:
        async def handler(client: CWClient):
            adj = seg(id)
            header = clean(await client.get(f"/procurement/adjustments/{adj}")) or {}
            details = await client.get_all(f"/procurement/adjustments/{adj}/details", max_rows=1000)
            return {**header, "details": clean(details)}

        return await run(settings, handler)

    @mcp.tool(
        name="cw_close_adjustment",
        description=(
            "Post an inventory adjustment (closedFlag = true). THIS MOVES STOCK and writes general ledger entries; "
            "a closed adjustment cannot be reopened, edited or deleted, only countered by another adjustment. "
            "Check it with cw_get_adjustment and confirm with the user first."
        ),
        annotations=DESTRUCTIVE,
        structured_output=False,
    )
    async def cw_close_adjustment(id: Annotated[int, Field(description="Adjustment ID to close and post")]) -> str:
        async def handler(client: CWClient):
            ops = [{"op": "replace", "path": "closedFlag", "value": True}]
            return clean(await client.patch(f"/procurement/adjustments/{seg(id)}", ops, idempotent=True))

        return await run(settings, handler)
