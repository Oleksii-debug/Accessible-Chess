# DEV4 SESSION HANDOFF

SESSION: 20260822-0109 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`
- Accepted manual5 integration observed: `manual5/integration-20260821` @ `e24ff85ff9a6ad3ea19d33f7035526c7bcdf2c8e`
- DEV5 active reconciliation observed: `manual5/dev5-reconcile-dev4-20260822` @ `09156cbca6bba0b6ba833cf3c867b127345014cf`, draft PR #66
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`
- Existing symlink regression commits: `d4e10e94a0f4d1ffb11e1d6190fb3c84e039d432`, `275b54669df4664d05775e92165c7c7f7397ee93`
- New PGN bounded-read regression commit: `a2fb7961f1e740b20927224dff54d10d6a9d5376`
- QA draft PR: #67

## Repository instruction discovery

`AGENTS.md` was not present on the checked live refs. Searches for `docs/codex/CURRENT_STATE.md`, `docs/codex/NEXT_WORK.md`, and `docs/codex/SESSION_HANDOFF.md` returned no live repository matches. The active Drive Full Product directive plus `docs/automation/DEV4_*` and canonical Drive handoffs therefore remain the operative DEV4 state sources.

## Findings

- `PROVEN_PRODUCT_DEFECT`: generic/ChessBase import provenance follows symlinks and can hash target bytes while losing the submitted indirection boundary.
- `PROVEN_PRODUCT_DEFECT`: PGN file opening performs an unbounded full-text `handle.read()` after hashing, violating active bounded-read/huge-file/resource-exhaustion fail-closed requirements. Strict QA test `tests/test_dev4_pgn_resource_security.py` was added without Product changes.
- `INCONCLUSIVE`: internal import/PGN errors and provenance retain paths, but user-facing absolute-path leakage has not yet been proven end-to-end.
- `PROVEN_PRODUCT_INTEGRATION_RISK`: naive DEV4 `stage1_board_actions.js` overwrite would regress accepted DEV1/integration semantics.
- `PROVEN_RELEASE_PIPELINE_BLOCKER`: Nuitka compiler report must not ship in user ZIP.
- `QA_OR_ENVIRONMENT_ONLY`: local checkout/testing unavailable because this execution environment could not resolve `github.com`; this does not alter Product classifications.
- `INCONCLUSIVE`: QA PR #67 Actions until a commit-associated run is observable.
- `HUMAN_ONLY`: exact fresh Windows native-menu/NVDA usability; `NVDA_VERIFIED=NO`.

## Evidence discipline

No local PASS is claimed. The PGN finding is based on direct live Product source showing unbounded `handle.read()` and the explicit active Drive contract requiring bounded reads and fail-closed huge-file/resource-exhaustion handling. The new QA regression is expected RED on current Product code, but no execution result is fabricated.

Existing accepted integration evidence remains:
- UI Semantic Gate `32515103291`: SUCCESS.
- Stage1 Saturation Hardening `32515103283`: SUCCESS.
These do not cover the new Full Product import-security assertions.

## Coordination / boundaries

DEV5 PR #66 is still open and owns the settings reconciliation slice. DEV4 did not modify that branch or integration. No Product source fix, force-push, `tools/qa`, strict Windows workflow, DEV3 ACSDB performance work, or Windows candidate was touched. Windows strict WIP=1 respected. No Ctrl+A/Ctrl+C Product defect claim. `NVDA_VERIFIED=NO`.

## Next action

Recheck PR #67 Actions, continue PGN/import resource and provenance audits, trace possible path leakage to actual user-facing surfaces, build the evidence-backed ChessBase capability matrix, and keep Stage1 reconciliation limited to DEV5/Audit-authorized slices.
