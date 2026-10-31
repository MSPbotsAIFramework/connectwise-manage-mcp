# 2026-10-31 Configuration item update tool (PRD-21611)

- New tool: `cw_update_configuration(id, operations)` — JSON Patch update of a configuration item
  (asset/CI) via `PATCH /company/configurations/{id}`, same shape as `cw_update_company` /
  `cw_update_ticket` (reuses `Operations` / `patch_ops` / `CWClient.patch`). Covers rename, set
  Inactive (`status/id`, `activeFlag`), and hardware field updates (`ram`, `osInfo`, `ipAddress`, etc.)
  via patch paths — any field ConnectWise's endpoint accepts, not a fixed list.
- Fix: `Operations` no longer declares a schema-level `min_length=1`. An empty `operations` array was
  previously rejected by FastMCP's argument validation with a raw `ToolError` before any handler ran,
  bypassing this connector's structured error envelope — affected `cw_update_configuration` as well as
  the already-shipped `cw_update_company` and `cw_update_ticket` (same shared type). `patch_ops()`
  already rejects an empty list with `ToolInputError` -> `{"error": {"code": "invalid_argument"}}`; that
  check is now the only enforcement path, so all three tools return a consistent envelope. No tool's
  required parameters or types changed (`tests/test_tools.py` backward-compat gate does not assert on
  `minItems`).
- All changes are additive; no existing tool's name or required parameter changed. 93 tools.
