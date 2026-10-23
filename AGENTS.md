# AGENTS.md

ConnectWise Manage (ConnectWise PSA) MCP server for the MSPbots Agent Platform. Python 3.12, uv, official `mcp`
SDK (FastMCP), Docker.

## Commands

- `uv sync`: install
- `uv run pytest -q`: tests
- `uv run ruff check . && uv run ruff format --check .`: lint
- `uv run connectwise-manage-mcp`: run on 0.0.0.0:8080 (`/mcp`, `/health`)
- `docker build -t connectwise-manage-mcp .`

## Layout

- `src/connectwise_manage_mcp/server.py`: FastMCP instance, instructions, HTTP app
- `src/connectwise_manage_mcp/credentials.py`: reads `X-CW-*` headers into a per-request ContextVar
  (presence check only; formats are validated inside tools)
- `src/connectwise_manage_mcp/api.py`: ConnectWise HTTP client (site URL normalisation, auth, retries, error mapping)
- `src/connectwise_manage_mcp/tools/`: one module per area; `_common.py` has paging, annotations, JSON Patch,
  conditions helpers, `run()` and the search / get tool factories
- `tests/fixtures/tools_baseline.json`: tools/list of the previous connector; the platform relies on it
- `tests/fixtures/tools_snapshot.json`: this server's parameters (`UPDATE_SNAPSHOT=1` to regenerate)

## Rules

- Credentials only from request headers; never from env, never cached across requests.
- The middleware only checks that the headers are present. The platform probes `tools/list` with placeholder
  values, so never validate header formats there.
- Stateless (`stateless_http=True`); no module-level mutable state.
- Tools return JSON strings; errors use the envelope in `_json.py`; tools never raise.
- Do not rename tools, remove parameters or add required parameters: agents on the platform depend on them.
  `tests/test_tools.py` enforces this against the baseline.
- ConnectWise silently drops unknown body fields: use the exact API field names and cover new bodies with a test.
- English only. No real credentials, hostnames, tenant or customer data anywhere, including tests and history.
- No third-party branding other than the ConnectWise product itself.
- Add dependencies with `uv add`; commit `uv.lock`.
- Record changes in `docs/changes/` and releases in `docs/releases/`.
