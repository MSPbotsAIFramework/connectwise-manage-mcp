# PRD-21610 · Code review

## Round 1 · 2026-10-31 · reviewed dev/PRD-21610 @ f01f41e (base main @ 83efef6)

Status: frozen @ f01f41e

Verdict: approved

### Scope

`git diff 83efef6...f01f41e -- src/ tests/ README.md docs/changes/` — one new tool
(`cw_list_agreement_types`) registered via the repo's existing `add_search()` factory in
`src/connectwise_manage_mcp/tools/finance.py`, plus the matching test/README/changelog updates
listed in the tech design's change list. No other file touched.

### Findings

None. No must-fix, no suggestions.

### Verification performed

- Re-ran the full suite independently on `dev/PRD-21610` @ `f01f41e`: `uv run pytest -q` →
  **94 passed**, 0 failed (matches the Self-test section).
- Re-ran `uv run ruff check .` → all checks passed; `uv run ruff format --check .` → 34 files
  already formatted.
- Re-ran the no-Chinese scan (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`)
  → clean.
- Diffed `README.md:12-82` (the Connector section) against
  `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md` → verbatim match
  (only a trailing-newline artifact of the diff extraction itself, no content difference).
- Confirmed `tests/fixtures/tools_snapshot.json` has exactly 94 entries including both
  `cw_list_agreement_types` (this ticket) and `cw_update_configuration` (PRD-21611, already merged
  into `main` before this ticket's base sync) — matches the `94` hardcoded in `README.md:124` and
  `tests/test_middleware.py:59`.
- Re-ran the four new tests individually plus `tests/test_tools.py`: 12 passed — matches the
  evidence recorded in `docs/tickets/PRD-21610.ac.json`.
- Read the merge commit `fd542e0` (base sync, `dev/PRD-21610` into `main` @ 83efef6) in full: the
  only real conflict was both tickets appending a literal to `tests/test_tools.py`'s `ADDED` set;
  both lines were kept (not a behavioral conflict — two independent new tool names). The three
  places that hardcode the *total* tool count (`README.md`, `tests/test_middleware.py`,
  `tests/fixtures/tools_snapshot.json`) were corrected to 94 consistently; verified above.
- `mbp.py mcplock info --repo connectwise-manage-mcp` → `locked: false` (dev-lock already released,
  nothing held).

### Contract self-check (SOP §14, items this change can affect)

- Credentials: unchanged, still Header-only (`X-CW-*`), no new header, no caching — not touched by
  this diff.
- Error envelope: reused as-is via `add_search()`, no new error path.
- README Connector section: verbatim match (see above).
- No Chinese: clean (see above).
- Items not applicable to this change: container/Dockerfile, health check, DNS-rebinding, lifespan
  wiring — none touched.

### Notes

- This is an additive, single-area change (one new read-only tool reusing an existing factory); the
  tech design identified no real alternative and the implementation matches the change list exactly
  (`finance.py`, `test_tools.py` ADDED set, `test_handlers.py`, `README.md`, `docs/changes/`).
- The base-sync merge conflict (`fd542e0`) was handled correctly per `toolchain.md` §6's four-step
  discipline: both sides' intent read and kept, the merged tree re-tested (94/94), and the
  resolution — including the two derived tool-count fixes — written up in the Self-test section
  with reasoning, not just a count of what changed.
