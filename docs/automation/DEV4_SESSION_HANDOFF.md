# DEV4 SESSION HANDOFF

SESSION: 20260822-0308 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact branches and SHAs

- DEV4 Stage1 Product source: `manual5/dev4-platform-security-packaging-20260821` @ `a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Manual5 integration: `manual5/integration-20260821` @ `0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation draft PR #66: `manual5/dev5-reconcile-dev4-20260822` @ `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`.
- DEV4 QA evidence branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New security evidence commit: `262ba68f4a5845335f463df7b8b67dcd7b6adb1a`.
- Subsequent handoff-only commits: `55f6430e2c9ab914150784b2197d282b135495e1`, `bf378eb3324f5f90614bde8000c16019b9b5bdf0`; verify live branch head after this file update before intake.
- QA draft PR: #67.

## Live CI

Manual5 integration exact SHA `0fa442330bc2bb03636ff9297512da4c29e38684`:
- UI Semantic Gate `32532577650` — SUCCESS.
- Stage1 Saturation Hardening `32532577641` — SUCCESS.

DEV5 reconciliation exact SHA `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`:
- UI Semantic Gate `32532415239` — SUCCESS.
- Stage1 Saturation Hardening `32532415296` — SUCCESS.

QA evidence commit `262ba68f4a5845335f463df7b8b67dcd7b6adb1a` has no observed commit-associated Actions. Classification: INCONCLUSIVE CI observability, not GREEN. Existing integration/DEV5 GREEN does not cover QA-only external-format assertions.

## Repository instruction discovery

`AGENTS.md` is absent on the checked repository ref. Requested `docs/codex/CURRENT_STATE.md`, `docs/codex/NEXT_WORK.md` and `docs/codex/SESSION_HANDOFF.md` are also absent. Active directive/handoff state is therefore live GitHub plus `docs/automation/DEV4_*` and canonical Drive DEV4 files.

## Findings

### PROVEN_PRODUCT_DEFECT — symlink/reparse import boundary

Generic import and ChessBase provenance/integrity/manifest paths follow filesystem indirection rather than failing closed. Strict QA coverage: `tests/test_dev4_chessbase_symlink_security.py`.

### PROVEN_PRODUCT_DEFECT — PGN unbounded resource boundary

`acs.pgn_service._read_text_snapshot()` performs an unbounded full-text `handle.read()` after bounded hashing, without explicit max source size or streaming parser boundary. Strict QA coverage: `tests/test_dev4_pgn_resource_security.py`.

### PROVEN_PRODUCT_DEFECT — serialized ChessBase report path leakage

Probe, integrity snapshot and bundle manifest report DTOs serialize absolute/local source paths. Strict QA coverage: `tests/test_dev4_chessbase_report_path_privacy.py`.

### PROVEN_PRODUCT_DEFECT — PGN optimistic-concurrency lost-update race

The implementation advertises `expected_sha256` as lost-update protection, but `save_pgn_atomic()` checks the current destination hash only before serialization/temp-file creation. It later performs unconditional `os.replace(tmp_path, destination)` with no destination revalidation. A writer that updates the destination after preflight but before replacement is silently overwritten.

DEV4 independently reproduced the state transition and added deterministic QA regression `tests/test_dev4_pgn_export_concurrency_security.py`. The test injects a competing destination write immediately before the replace boundary and requires `PgnConcurrentWriteError` plus preservation of the newer content. Current Product ordering cannot satisfy that contract. No Product source fix is included.

QA evidence commit:
- `262ba68f4a5845335f463df7b8b67dcd7b6adb1a` — `test(security): gate PGN atomic lost-update race`.

## Preserved findings / boundaries

- `docs/automation/DEV4_CHESSBASE_CAPABILITY_MATRIX.md` remains evidence-only and does not infer proprietary decoder compatibility from suffix recognition.
- PROVEN_PRODUCT_INTEGRATION_RISK: preserve accepted DEV1/integration `web/stage1_board_actions.js` semantics.
- PROVEN_RELEASE_PIPELINE_BLOCKER: `nuitka-compilation-report.xml` must remain CI evidence only and stay out of user ZIPs.
- HUMAN_ONLY: exact fresh Windows native-menu/NVDA usability. `NVDA_VERIFIED=NO`.
- No Ctrl+A/Ctrl+C Product defect claim.
- Windows strict WIP=1 respected.
- No force-push, DEV5/integration mutation, `tools/qa` or strict Windows workflow edit, DEV3 ACSDB performance takeover, frozen release merge or Windows candidate.

## Next action

Recheck final QA branch head and PR #67 Actions. Continue PGN export failure-recovery/path-indirection audit, then generic import size/encoding/cancellation limits and end-to-end path/error exposure tracing. Continue ChessBase unknown-version/resource-boundary evidence without inventing proprietary semantics. Re-enter Stage1 package work only through DEV5/Audit-authorized reconciliation.
