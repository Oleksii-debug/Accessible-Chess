# DEV4 RUN STATE

RUN_ID: 20260822-1436-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Product source: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration: `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684` (live compare IDENTICAL at run start).
- DEV5 reconciliation PR #66 remains separate and OPEN/DRAFT at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; DEV4 did not mutate it.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New strict evidence commit: `4f41b583755fca475becaf97eea6a7d8e9b20b7e` — `test(security): gate persisted import error privacy`.
- QA PR #67 remains OPEN/DRAFT/MERGEABLE; metadata commits follow the evidence commit, so final exact branch head must be read live after synchronization.
- Exact QA evidence-commit Actions: none observed at inspection time; classification `INCONCLUSIVE`, not GREEN.
- Local clean-checkout attempt failed because the execution sandbox could not resolve `github.com`; classification `QA_OR_ENVIRONMENT_ONLY`, not Product evidence.
- `AGENTS.md` and shared `docs/codex/{CURRENT_STATE,NEXT_WORK,SESSION_HANDOFF}.md` remain absent on the inspected QA ref.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New PROVEN_PRODUCT_DEFECT — raw failed-import diagnostics cross a persisted application boundary

`AcsDatabase.import_pgn_text()` catches arbitrary exceptions, persists `f"{type(exc).__name__}: {exc}"` into `import_attempts.error_message`, and re-raises. `ImportHistoryService` later returns that persisted `error_message` unchanged to application callers. A low-level parser/importer/provider exception containing a private workstation path or secret-like diagnostic value therefore crosses both the ACSDB persistence boundary and the application-facing import-history boundary verbatim.

Strict deterministic gate: `tests/test_dev4_import_history_error_privacy.py`. It injects a parser failure containing a synthetic private Windows path and credential-like diagnostic, then requires failed import history to preserve the failure record without preserving those private details. Product code intentionally unchanged.

## Locked PROVEN_PRODUCT_DEFECT findings

1. Import/ChessBase symlink-reparse indirection follows targets instead of failing closed.
2. PGN import lacks a bounded full-text/resource boundary and finite source cap.
3. ChessBase serialized probe/integrity/manifest DTOs expose absolute local paths.
4. PGN `expected_sha256` overwrite has a TOCTOU lost-update race.
5. PGN `overwrite=False` can clobber a destination created after preflight.
6. PGN export filesystem indirection is not fail-closed.
7. ChessBase companion-directory I/O failures collapse into ordinary no-companion evidence.
8. Generic import `inspect_batch()` aborts on importer `RuntimeError` instead of recording and continuing.
9. ChessBase manifest re-verification propagates hash/open I/O failure instead of returning explicit failed-verification evidence.
10. Shared import fingerprinting can open FIFO/special files before fail-closed type validation.
11. Shared import fingerprinting can return provenance while the source mutates during hashing instead of rejecting the unstable snapshot.
12. ACSDB failed-import history persists raw exception text and exposes it through `ImportHistoryService`, leaking private path/provider detail across a concrete persisted/application sink.

## Other classifications

- QA EVIDENCE: PGN export recovery/temp cleanup and POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish provider path errors are sanitized.
- QA_OR_ENVIRONMENT_ONLY: this sandbox could not resolve GitHub for a clean local checkout/test run.
- INCONCLUSIVE: exact QA-head CI until checks appear.
- INCONCLUSIVE: PGN parent-directory crash/power-loss durability.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck PR #67 final exact head and Actions. Continue generic import cancellation/encoding/truncation evidence and ChessBase component snapshot/open/stat/hash observability. Trace further errors only into concrete persisted/UI/report sinks. Stay in SAFE OVERLAP and out of Windows strict/Product-owner lanes.
