# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Finance: agreements, agreement additions, agreement recaps and invoices."""

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

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
    apply_patch,
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

BillCustomer = Literal["Billable", "DoNotBill", "NoCharge"]

INVOICE_SCALAR_PATHS = {"attention", "dueDate", "date", "reference", "customerPO", "internalNotes"}
INVOICE_REF_PATHS = {"status", "billToCompany", "billingSite"}


def invoice_ops(ops: list[dict]) -> list[dict]:
    """Restrict invoice patches to the fields agents are allowed to change."""
    out = []
    for op in ops:
        parts = op["path"].strip("/").split("/")
        if parts[0] == "billToSite":
            parts[0] = "billingSite"
        path = "/".join(parts)
        if len(parts) == 1 and parts[0] in INVOICE_SCALAR_PATHS:
            pass
        elif parts[0] in INVOICE_REF_PATHS and (len(parts) == 1 or (len(parts) == 2 and parts[1] == "id")):
            if op["op"] != "remove":
                value = op.get("value")
                if len(parts) == 2 and not (isinstance(value, int) and not isinstance(value, bool)):
                    raise ToolInputError(f"{path} needs a numeric ID.")
                if len(parts) == 1 and not (isinstance(value, dict) and isinstance(value.get("id"), int)):
                    raise ToolInputError(f'{path} needs an object like {{"id": 5}}.')
        else:
            raise ToolInputError(
                f"Path {op['path']!r} is not allowed. Allowed: status[/id], billToCompany[/id], billingSite[/id] "
                "(alias billToSite), attention, dueDate, date, reference, customerPO, internalNotes."
            )
        out.append({**op, "path": path})
    return out


def register(mcp: FastMCP, settings: Settings) -> None:
    add_search(
        mcp,
        settings,
        name="cw_search_agreements",
        description=(
            "Search finance agreements (recurring revenue contracts), e.g. conditions cancelledFlag = false or "
            'company/name = "Acme".'
        ),
        path="/finance/agreements",
    )
    add_get(
        mcp,
        settings,
        name="cw_get_agreement",
        description="Get a specific finance agreement by ID.",
        path="/finance/agreements/{id}",
        id_help="Agreement ID",
    )
    add_search(
        mcp,
        settings,
        name="cw_list_agreement_types",
        description="List agreement (contract) types in ConnectWise Manage, e.g. the tiers used on finance agreements.",
        path="/finance/agreements/types",
    )

    @mcp.tool(
        name="cw_get_agreement_additions",
        description="Get additions (recurring line items) of a specific agreement.",
        annotations=READ,
        structured_output=False,
    )
    async def cw_get_agreement_additions(
        agreementId: Annotated[int, Field(description="Agreement ID")],
        page: Page = None,
        pageSize: PageSize = None,
        conditions: Annotated[str | None, Field(description="Optional ConnectWise conditions query string")] = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            params = {"conditions": join_conditions(conditions), "page": number, "pageSize": size}
            rows, has_next = await client.get_page(f"/finance/agreements/{seg(agreementId)}/additions", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    add_search(
        mcp,
        settings,
        name="cw_search_agreement_recaps",
        description=(
            "Search agreement recaps: the billing rollup per agreement (starting, used, remaining, available and "
            "overrun amounts, unbilled periods, last and next invoice). Use for burn-down and overage questions."
        ),
        path="/finance/agreementrecap",
        conditions_help='ConnectWise conditions query string (e.g. companyName like "%Acme%")',
        order_help="Field to order by (e.g. 'remainingAmount asc')",
    )

    @mcp.tool(
        name="cw_get_agreement_recap",
        description="Get the billing recap for a specific agreement by agreement ID.",
        annotations=READ,
        structured_output=False,
    )
    async def cw_get_agreement_recap(id: Annotated[int, Field(description="Agreement ID")]) -> str:
        async def handler(client: CWClient):
            agreement = seg(id)
            rows: list = []
            for cond in (f"agreementId = {agreement}", f"id = {agreement}"):
                try:
                    rows, _ = await client.get_page("/finance/agreementrecap", {"conditions": cond, "pageSize": 1})
                except ApiError as exc:
                    if exc.code == "invalid_argument":
                        continue
                    raise
                if rows:
                    break
            if not rows:
                raise ApiError("not_found", f"No agreement recap for agreement {agreement}.")
            return clean(rows[0])

        return await run(settings, handler)

    @mcp.tool(
        name="cw_update_agreement_addition",
        description=(
            "Update an agreement addition (recurring line item) with JSON Patch, e.g. seat-count reconciliation. "
            "Common paths: quantity, effectiveDate, cancelledDate, billCustomer (Billable, DoNotBill, NoCharge), "
            "description, invoiceDescription, unitPrice, unitCost. dryRun previews the result without saving."
        ),
        annotations=UPDATE,
        structured_output=False,
    )
    async def cw_update_agreement_addition(
        agreementId: Annotated[int, Field(description="Agreement ID")],
        additionId: Annotated[int, Field(description="Addition (line item) ID")],
        operations: Operations,
        dryRun: Annotated[
            bool | None, Field(description="If true, fetch the addition, apply the patch locally and return it unsaved")
        ] = None,
    ) -> str:
        async def handler(client: CWClient):
            ops, replace_only = patch_ops(operations)
            path = f"/finance/agreements/{seg(agreementId)}/additions/{seg(additionId)}"
            if dryRun:
                current = await client.get(path) or {}
                return {"dryRun": True, "saved": False, "preview": clean(apply_patch(current, ops))}
            return clean(await client.patch(path, ops, idempotent=replace_only))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_create_agreement_addition",
        description=(
            "Create an addition (recurring line item) on an agreement. Needs a catalog item (productId) and "
            "billCustomer."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_create_agreement_addition(
        agreementId: Annotated[int, Field(description="Agreement ID")],
        productId: Annotated[int, Field(description="Catalog item (product) ID to add")],
        billCustomer: Annotated[BillCustomer, Field(description="Billing treatment for this addition")],
        quantity: Annotated[float | None, Field(description="Quantity")] = None,
        description: Annotated[str | None, Field(description="Line description")] = None,
        invoiceDescription: Annotated[str | None, Field(description="Description shown on the invoice")] = None,
        effectiveDate: Annotated[str | None, Field(description="Effective date (ISO 8601)")] = None,
        cancelledDate: Annotated[str | None, Field(description="Cancelled date (ISO 8601)")] = None,
        unitPrice: Annotated[float | None, Field(description="Unit price")] = None,
        unitCost: Annotated[float | None, Field(description="Unit cost")] = None,
        taxableFlag: Annotated[bool | None, Field(description="Whether this addition is taxable")] = None,
        uom: Annotated[str | None, Field(description="Unit of measure")] = None,
    ) -> str:
        async def handler(client: CWClient):
            payload = body(
                product=ref(productId),
                billCustomer=billCustomer,
                quantity=quantity,
                description=description,
                invoiceDescription=invoiceDescription,
                effectiveDate=effectiveDate,
                cancelledDate=cancelledDate,
                unitPrice=unitPrice,
                unitCost=unitCost,
                taxableFlag=taxableFlag,
                uom=uom,
            )
            return clean(await client.post(f"/finance/agreements/{seg(agreementId)}/additions", payload))

        return await run(settings, handler)

    add_search(
        mcp,
        settings,
        name="cw_search_invoices",
        description="Search invoices in ConnectWise Manage.",
        path="/finance/invoices",
        conditions_help='ConnectWise conditions query string (e.g. company/name = "Acme")',
    )
    add_get(
        mcp,
        settings,
        name="cw_get_invoice",
        description="Get a specific invoice by ID.",
        path="/finance/invoices/{id}",
        id_help="Invoice ID",
    )

    @mcp.tool(
        name="cw_update_invoice",
        description=(
            "Update one invoice with JSON Patch. Allowed paths: status/id (numeric) or status ({id}), attention, "
            "dueDate, date, reference, customerPO, internalNotes, billToCompany[/id], billingSite[/id] (alias "
            "billToSite). Other paths are rejected. Resolve status names to IDs first; never guess an ID. "
            "dryRun previews without saving. Needs Finance > Invoices: Edit."
        ),
        annotations=DESTRUCTIVE,
        structured_output=False,
    )
    async def cw_update_invoice(
        id: Annotated[int, Field(description="Invoice ID", gt=0)],
        operations: Operations,
        dryRun: Annotated[
            bool | None, Field(description="If true, fetch the invoice, apply the patch locally and return it unsaved")
        ] = None,
    ) -> str:
        async def handler(client: CWClient):
            ops, replace_only = patch_ops(operations)
            ops = invoice_ops(ops)
            path = f"/finance/invoices/{seg(id)}"
            if dryRun:
                current = await client.get(path) or {}
                return {"dryRun": True, "saved": False, "preview": clean(apply_patch(current, ops))}
            return clean(await client.patch(path, ops, idempotent=replace_only))

        return await run(settings, handler)
