# PRD-21611 · Code review

## Round 1 · 2026-10-31 · reviewed dev/PRD-21611 @ 591f0a8 (base main @ b082cc5)

Verdict: approved

### Scope checked

`git diff b082cc5...591f0a8`: `src/connectwise_manage_mcp/tools/system.py`, `src/connectwise_manage_mcp/tools/_common.py`,
`tests/test_handlers.py`, `tests/test_tools.py`, `tests/test_middleware.py`, `tests/fixtures/tools_snapshot.json`,
`README.md`, `docs/changes/2026-10-31-configuration-item-update.md`, plus `docs/tickets/PRD-21611.md` /
`PRD-21611.ac.json` (design + self-test docs). No other ticket's commits are on this branch
(`ad1f010`, `6c7052e`, `2f20f08` only).

### Findings

No must-fix findings.

1. [suggestion] `src/connectwise_manage_mcp/tools/_common.py:200-204` — the comment explaining why
   `min_length=1` was dropped from `Operations` is good and should stay, but consider also noting in the
   docstring of `patch_ops()` itself (not just at the call site) that it is now the sole enforcement point
   for "non-empty operations" across all eight tools that import `Operations`. Not required — the existing
   comment and the self-test section already make this traceable from the diff.

### Verification notes

- `cw_update_configuration` (`system.py:94-112`) is byte-for-byte the same shape as `cw_update_company`
  (`companies.py:129-144`) and `cw_update_ticket` (`tickets.py:159-175`): same `Operations` parameter,
  same `patch_ops()` → `CWClient.patch()` → `clean()` pipeline, same `UPDATE` annotation,
  `structured_output=False`. Matches the tech design's Option A exactly; Option B/C were correctly
  rejected for the reasons stated (parameter-list churn vs. the connector's own established pattern,
  and not overloading `cw_update_ticket_configurations`'s different contract).
- The `Operations` type (`_common.py:204`) is shared by 8 tools across `system.py`, `companies.py`,
  `tickets.py`, `contacts.py`, `time_entries.py`, `finance.py` (×2), `catalog.py`, `schedule.py` — checked
  every call site (`grep -n "patch_ops(operations"`) and confirmed all eight call `patch_ops(operations)`
  with the default `value_required=True`, which independently raises `ToolInputError` →
  `{"error": {"code": "invalid_argument"}}` on an empty list. Removing the schema-level `min_length=1` is
  therefore safe for all eight tools, not just the new one — this is a real pre-existing bug fix
  (`cw_update_company`/`cw_update_ticket` previously leaked a raw `ToolError` on an empty array instead of
  the connector's structured envelope), in scope because this ticket already touches `_common.py`, and
  reversible (single-line change, documented in `docs/changes/2026-10-31-configuration-item-update.md`).
  This is a *compatible* widening of accepted input (SOP §13: relaxing a constraint, not tightening one),
  so it does not require advance platform notification as a breaking change.
- `tests/test_tools.py::test_parameters_are_backward_compatible` (read in full, `:68-87`) asserts on
  parameter presence, required-set, JSON-schema `type`, and `enum` only — it does not assert on
  `minItems`/`min_length`, confirming the self-test's claim that the compatibility gate is unaffected by
  the `Operations` change. `ADDED` correctly gained `cw_update_configuration`; `BASELINE` (87, the frozen
  prior-connector snapshot) is untouched, per `AGENTS.md`'s "baseline never changes" rule.
- Independently re-ran the gates on commit `591f0a8` (same as `2f20f08` for source; `591f0a8` only adds
  the frozen docs on top) in a fresh worktree: `uv sync` → `uv run pytest -q` → **90 passed, 0 failed**;
  `uv run ruff check .` → all checks passed; `uv run ruff format --check .` → 31 files already formatted;
  `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` → no matches (exit 1). All
  match the Self-test section's reported results.
- README `Connector` section (`README.md`, MSPbots banner through the standard footer) diffed against
  `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md`: verbatim substring
  match, unaffected by this change.
- Tool-count bookkeeping is consistent everywhere it appears in code: `README.md:124` → "93 tools",
  `tests/test_middleware.py:59` → `== 93`, `tests/test_tools.py` `ADDED` includes the new name. No stray
  `92` reference remains in source or tests (only in the ticket's own historical record of "before" state,
  which is expected).
- Credentials/statelessness: the new tool introduces no new credential path, no module-level state, and no
  argument logging — reads headers the same way every other tool in this connector does (unchanged;
  `credentials.py` is not touched by this diff). AC7 (needs a live ConnectWise account) is correctly
  recorded as `untested` with a reason, not claimed as a pass — consistent with the vendor-mcp rule that a
  missing vendor test account is not a blocker.
- `ac.json`: all 6 automated cases (TC-CWM-001..006) have `result: pass` with a specific pytest invocation
  and output as evidence; TC-CWM-007 is `untested` with a clear reason. No case was altered to fit the
  implementation (cross-checked against the Product design's AC1-AC7, which the test cases map to 1:1).
- `docs/changes/2026-10-31-configuration-item-update.md` follows the repo's own convention
  (`AGENTS.md`: "Record changes in `docs/changes/`"); no `docs/releases/` entry was added, consistent with
  the prior ticket's precedent (`2026-10-25-ticket-classification-and-billing.md` also added no releases
  entry) — not a gap introduced by this ticket.

### REVIEW.md checklist

No BLOCKER from `references/REVIEW.md` §2 applies: gates pass (0 exit codes, re-verified independently),
no new test failures, no red/unreasoned test cases, counts parsed cleanly (90 passed is an explicit
number), no schema/migration in this connector (stateless, no DB), nothing bypassed (`--no-check`/
`--no-migrate` have no equivalent in this repo per the Handoff section), no packaging or protected-branch
action taken by the dev leg, no merge conflicts yet (nothing merged), base was the connector's only
possible base (`main`, read fresh from `origin/main` at review time — still at `b082cc5`, matching the
Handoff's stated baseline), no DROP/type change (no DB), no reuse violation (change reuses 100% of
existing helpers; the one new line of logic, `_common.py`'s `min_length` removal, is a fix not a
duplication).

Status: frozen @ 591f0a8
