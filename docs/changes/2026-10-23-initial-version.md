# 2026-10-23 Initial version

First release of the MSPbots ConnectWise Manage (ConnectWise PSA) MCP server, written from the public
ConnectWise PSA REST API documentation (API 3.0).

- 87 tools covering service tickets, notes and ticket configurations, board setup, companies and sites,
  contacts (communication items, contact types), projects and project tickets, time entries, schedule
  entries, members, configurations, activities, catalog, inventory and adjustments, agreements,
  agreement additions and recaps, invoices, opportunities, sales orders, purchase orders and
  procurement products.
- Tool names and parameters are compatible with the previous ConnectWise Manage connector on the
  platform (`tests/fixtures/tools_baseline.json`). Every baseline parameter is implemented; none is
  ignored.
- New optional parameters: `fields` on the generic search / list tools, `page` on `cw_list_sites` and
  `cw_list_contact_types`, `conditions` on `cw_get_agreement_additions`.
- Credentials: `X-CW-Url`, `X-CW-Company-Id`, `X-CW-Public-Key`, `X-CW-Private-Key`, `X-CW-Client-Id`
  (all required). The middleware only checks presence; the site URL is normalised and validated inside
  each tool call (`invalid_argument` when unusable).

## Behaviour differences from the previous connector

- `pageSize` is capped at 200 (was 1000); use `has_more` and `page` to continue. `cw_list_sites` and
  `cw_list_contact_types` default to 50 per page (was 100).
- List tools return `{"items", "count", "page", "page_size", "has_more"}` instead of a bare array.
  The `*_href` links and the `_info` blocks of nested references are removed from all results.
- Single-quoted string literals in any `conditions` are converted to double quotes (ConnectWise syntax).
- `cw_update_ticket_configurations` reports failures with `failed` > 0 and per-operation `success`
  instead of setting the MCP `isError` flag (tools here never raise).
- `cw_get_ticket_notes` / `cw_get_project_ticket_notes` return the ticket's own notes in `items`; on
  page 1 the notes of up to 10 child tickets (`parentTicketId`) are added under `child_tickets`.
- Retries follow one policy for all tools: 429 is retried up to 3 times honouring `Retry-After`; 5xx and
  timeouts are retried only for reads, deletes and replace-only patches. `cw_update_invoice` previously
  retried once.
- `cw_update_invoice` no longer lists instance-specific billing status IDs in its description; resolve
  status IDs on the tenant's own instance.
- `cw_test_connection` returns `status`, `message` and selected `/system/info` fields (version, isCloud,
  serverTimeZone, licenseBits, cloudRegion) rather than the whole system info object.
- `cw_get_inventory_on_hand` scans at most 200 bins per call (flagged with `has_more` and a note) and
  stops early before the call time budget runs out. Serial numbers are returned only when the bin's
  on-hand rows carry them; there is no separate serial-number lookup.
- `cw_get_agreement_recap` looks the recap up with `agreementId = <id>` and falls back to `id = <id>`.
- `cw_create_company` sends `country` as `{"id": n}` when it is digits and `{"name": "..."}` otherwise.
- `cw_update_contact` rejects patches to `types` up front and points to `cw_update_contact_types`.
- `cw_update_contact_types` remove for a type the contact does not have returns `not_found`.

## Not verified against a live instance

No ConnectWise instance was available while writing this version; all behaviour is covered by tests
against a mocked API. Worth checking on a sandbox first: the `inventoryOnHand` row field names
(`onHand`, `serialNumbers`), the `agreementrecap` lookup condition, `parentTicketId` filtering on project
tickets, and company `country` by name.
