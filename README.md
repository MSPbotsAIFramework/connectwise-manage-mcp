# ConnectWise Manage MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server that lets AI agents on the
MSPbots Agent Platform work in ConnectWise Manage (ConnectWise PSA): service tickets and notes,
companies, contacts, projects, time and schedule entries, members, configurations, activities,
the product catalog, inventory, agreements, invoices, opportunities, purchase and sales orders.

It runs as a stateless HTTP service behind the MSPbots MCP gateway. The gateway sends each
tenant's ConnectWise credentials as request headers on every call; the server keeps nothing between
requests.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Credentials (request headers)

| Header | Required | Meaning |
|---|---|---|
| `X-CW-Url` | Yes | ConnectWise site, e.g. `https://na.myconnectwise.net` (or `api-na.myconnectwise.net`, `eu.myconnectwise.net`, an on-premises host). `https://` and the `/v4_6_release/apis/3.0` path are optional; a full API path with another codebase is kept as given. |
| `X-CW-Company-Id` | Yes | The company ID used to sign in to ConnectWise. |
| `X-CW-Public-Key` | Yes | Public key of an API member (**System > Members > API Members > API Keys**). |
| `X-CW-Private-Key` | Yes | Private key of the same API key. |
| `X-CW-Client-Id` | Yes | ConnectWise developer client ID (sent as the `clientId` header). Injected by the platform. |

Requests are authenticated with HTTP Basic `<companyId>+<publicKey>:<privateKey>` plus the `clientId`
header, as the ConnectWise developer documentation describes. What the agent can see and change is
limited by the API member's security role.

Header names are case-insensitive. A request to `/mcp` with any of these headers missing or blank gets
`401` with the list of expected headers. The server does not check header formats before a tool runs
(the platform probes `initialize` and `tools/list` with placeholder values); an unusable site URL is
reported by the tool as `invalid_argument`.

## Tools

| Area | Tools |
|---|---|
| Service tickets | `cw_search_tickets`, `cw_get_ticket`, `cw_create_ticket`, `cw_update_ticket`, `cw_get_ticket_notes`, `cw_add_ticket_note`, `cw_get_ticket_configurations`, `cw_update_ticket_configurations` |
| Board setup | `cw_list_boards`, `cw_list_statuses`, `cw_list_priorities`, `cw_list_ticket_types`, `cw_list_ticket_subtypes`, `cw_list_ticket_items` |
| Companies | `cw_search_companies`, `cw_get_company`, `cw_create_company`, `cw_update_company`, `cw_list_sites` |
| Contacts | `cw_search_contacts`, `cw_get_contact`, `cw_create_contact`, `cw_update_contact`, `cw_add_contact_communication`, `cw_update_contact_communication`, `cw_list_contact_types`, `cw_update_contact_types` |
| Projects | `cw_search_projects`, `cw_get_project`, `cw_create_project`, `cw_search_project_tickets`, `cw_get_project_ticket`, `cw_get_project_ticket_notes`, `cw_add_project_ticket_note` |
| Time | `cw_search_time_entries`, `cw_get_time_entry`, `cw_create_time_entry`, `cw_update_time_entry`, `cw_delete_time_entry`, `cw_list_work_types`, `cw_list_work_roles` |
| Schedule | `cw_search_schedule_entries`, `cw_list_schedule_types`, `cw_list_schedule_statuses`, `cw_create_schedule_entry`, `cw_update_schedule_entry` |
| Members and configurations | `cw_search_members`, `cw_get_member`, `cw_search_configurations`, `cw_get_configuration` |
| Activities | `cw_search_activities`, `cw_get_activity`, `cw_create_activity` |
| Catalog | `cw_search_catalog_items`, `cw_get_catalog_item`, `cw_create_catalog_item`, `cw_update_catalog_item`, `cw_list_catalog_categories`, `cw_list_catalog_subcategories`, `cw_list_manufacturers` |
| Inventory | `cw_list_warehouses`, `cw_list_warehouse_bins`, `cw_get_inventory_on_hand`, `cw_list_adjustment_types`, `cw_create_adjustment`, `cw_add_adjustment_detail`, `cw_get_adjustment`, `cw_close_adjustment` |
| Agreements | `cw_search_agreements`, `cw_get_agreement`, `cw_list_agreement_types`, `cw_get_agreement_additions`, `cw_create_agreement_addition`, `cw_update_agreement_addition`, `cw_search_agreement_recaps`, `cw_get_agreement_recap` |
| Invoices | `cw_search_invoices`, `cw_get_invoice`, `cw_update_invoice` |
| Sales | `cw_search_opportunities`, `cw_get_opportunity`, `cw_search_opportunity_forecasts`, `cw_search_opportunity_notes`, `cw_search_sales_stages`, `cw_search_sales_orders`, `cw_get_sales_order`, `cw_get_sales_order_products` |
| Procurement | `cw_search_purchase_orders`, `cw_get_purchase_order`, `cw_get_purchase_order_items`, `cw_search_procurement_products`, `cw_get_procurement_product` |
| Diagnostics | `cw_test_connection` |

93 tools. Tool names and parameters match the previous ConnectWise Manage connector on the MSPbots
Agent Platform, so existing agents keep working. That compatibility is why this is one server with
more than 20 tools instead of several smaller ones.

Behaviour notes:

- Every tool returns a JSON string. Errors use one envelope:
  `{"error": {"code": "...", "message": "...", "retryable": false}}` with `code` one of
  `not_configured`, `unauthorized`, `not_found`, `invalid_argument`, `rate_limited`, `upstream_error`.
- List tools return `{"items", "count", "page", "page_size", "has_more"}`. `pageSize` defaults to 25
  (50 for `cw_list_sites` and `cw_list_contact_types`) and is capped at 200. Results larger than
  20,000 characters are cut and flagged with `truncated` / `has_more`. The `*_href` links ConnectWise
  adds to every object are removed.
- `conditions` use ConnectWise syntax: strings in double quotes, dates in square brackets
  (`dateStart >= [2026-01-01T00:00:00Z]`). Single-quoted literals are converted to double quotes.
- Updates are JSON Patch arrays (`op`, `path`, `value`); `add` and `replace` need a `value`.
- ConnectWise silently drops unknown fields in request bodies, so the tools send exact API field names.
- Contacts: types are set at creation as `types: [{"id": n}]` and changed later with
  `cw_update_contact_types` (type associations). Contact types keep their label in `description`;
  `name` in `cw_list_contact_types` conditions is rewritten. `cw_search_contacts` rewrites a bare
  `name = "..."` into first / last name conditions and filters types through `childConditions`.
  There is no delete-contact tool: deactivate with `inactiveFlag`.
- `cw_add_ticket_note` emails nobody unless an email flag is set.
- `cw_update_invoice` only accepts the documented invoice paths; `cw_update_invoice` and
  `cw_update_agreement_addition` support `dryRun`.
- Transient failures are retried with backoff, honouring `Retry-After`: 429 always, 5xx and timeouts
  only for requests that are safe to repeat (reads, deletes, replace-only patches), so creates are
  never duplicated. One tool call stays under 100 seconds.

## Run locally

```bash
uv sync
uv run connectwise-manage-mcp            # listens on 0.0.0.0:8080
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'X-CW-Url: https://na.myconnectwise.net' -H 'X-CW-Company-Id: YOUR_COMPANY_ID' \
  -H 'X-CW-Public-Key: YOUR_PUBLIC_KEY' -H 'X-CW-Private-Key: YOUR_PRIVATE_KEY' \
  -H 'X-CW-Client-Id: YOUR_CLIENT_ID' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Environment variables (all optional): `MCP_HTTP_HOST` (default `0.0.0.0`), `MCP_HTTP_PORT`
(default `8080`), `MCP_TRANSPORT` (`http` or `stdio`). Unknown variables are ignored. Credentials
are never read from the environment.

## Docker

```bash
docker build -t connectwise-manage-mcp .
docker run --rm -p 8080:8080 connectwise-manage-mcp
```

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

Code is in `src/connectwise_manage_mcp/` (one module per area under `tools/`), tests in `tests/`.
The implementation follows the public ConnectWise PSA REST API documentation at
https://developer.connectwise.com/.

## License

Copyright 2026 MSPbots.ai. Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE)
and [NOTICE](NOTICE).

ConnectWise is a trademark of its owner. This project is not affiliated with or endorsed by ConnectWise.
