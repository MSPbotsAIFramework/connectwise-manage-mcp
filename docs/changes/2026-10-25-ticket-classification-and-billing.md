# 2026-10-25 Ticket classification and time entry billing (PRD-20969)

- New tools:
  - `cw_list_ticket_types` (per board, `/service/boards/{id}/types`)
  - `cw_list_ticket_subtypes` (per board; with `typeId`, only the subtypes associated with that type)
  - `cw_list_ticket_items` (per board; with `typeId` / `subTypeId`, only the associated items)
  - `cw_list_work_types` (`/time/workTypes`), `cw_list_work_roles` (`/time/workRoles`)
- The type / subtype filters read the board's `typeSubTypeItemAssociations` and return distinct `{id, name}` entries.
- `cw_create_time_entry`: new optional `billableOption` (`Billable`, `DoNotBill`, `NoCharge`, `NoDefault`),
  `addToDetailDescriptionFlag`, `addToInternalAnalysisFlag`, `addToResolutionFlag`.
- `cw_create_ticket`: new optional `itemId`.
- All changes are additive; no existing parameter changed.
