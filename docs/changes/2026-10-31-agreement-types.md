# 2026-10-31 Agreement types lookup (PRD-21610)

- New tool: `cw_list_agreement_types` (`/finance/agreements/types`) — lists ConnectWise Manage
  agreement (contract) types, via the existing `add_search()` factory (`conditions`, `fields`,
  `orderBy`, `page`, `pageSize`), same shape as `cw_list_boards` / `cw_list_priorities` /
  `cw_list_work_types` / `cw_list_work_roles`.
- No existing tool's name, parameter, or response shape changed.
