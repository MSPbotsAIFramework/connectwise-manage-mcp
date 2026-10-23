# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""FastMCP server and HTTP app."""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import Settings
from .credentials import CredentialMiddleware
from .tools import (
    catalog,
    companies,
    contacts,
    finance,
    inventory,
    projects,
    sales,
    schedule,
    system,
    tickets,
    time_entries,
)

INSTRUCTIONS = (
    "ConnectWise Manage (ConnectWise PSA) is the MSP's ticketing, project, time, sales, procurement and billing "
    "system. Most records belong to a company: find it with cw_search_companies, then filter other searches "
    "with conditions such as company/id = 5. Conditions use ConnectWise syntax: strings in double quotes, "
    "dates in square brackets in UTC, e.g. dateStart >= [2026-01-01T00:00:00Z]; combine with and / or. "
    "Updates are JSON Patch operations (op, path, value). Look up IDs (boards, statuses, priorities, members, "
    "types) with the list tools instead of guessing. Contacts cannot be deleted: set inactiveFlag. Ask the user "
    "before deleting time entries, posting inventory adjustments or changing invoices."
)

MODULES = (
    tickets,
    companies,
    contacts,
    projects,
    time_entries,
    schedule,
    system,
    catalog,
    inventory,
    finance,
    sales,
)


def create_mcp(settings: Settings) -> FastMCP:
    mcp = FastMCP(
        name="connectwise-manage-mcp",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        # The gateway forwards requests with its own Host header; DNS-rebinding
        # protection would reject them with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    for module in MODULES:
        module.register(mcp, settings)
    return mcp


def create_app(settings: Settings) -> Starlette:
    mcp = create_mcp(settings)
    mcp_app = mcp.streamable_http_app()

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # Mount() does not run a sub-app's lifespan; without forwarding it the
    # session manager never starts and /mcp fails while /health still passes.
    return Starlette(
        routes=[Route("/health", health), Mount("/", app=CredentialMiddleware(mcp_app))],
        lifespan=lambda app: mcp_app.router.lifespan_context(app),
    )
