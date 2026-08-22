# DEV4 SESSION HANDOFF

SESSION: 20260822-1436 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact state basis

- DEV4 Product: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration: `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation PR #66 remains separate at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29` and was not mutated.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New evidence commit: `4f41b583755fca475becaf97eea6a7d8e9b20b7e` — `test(security): gate persisted import error privacy`.
- QA PR #67 remains OPEN/DRAFT/MERGEABLE. Metadata commits follow the evidence commit; final exact branch head must be read live after synchronization.
- Exact QA CI remains `INCONCLUSIVE` until commit-associated Actions are observed.
- Local clean-checkout was blocked by sandbox DNS failure resolving `github.com`; `QA_OR_ENVIRONMENT_ONLY`, not Product evidence.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New finding

`PROVEN_PRODUCT_DEFECT` — failed ACSDB import diagnostics cross a concrete persisted/application-facing privacy boundary. `AcsDatabase.import_pgn_text()` stores raw exception type/text in `import_attempts.error_message`; `ImportHistoryService` returns that field unchanged. A parser/importer/provider exception carrying a private local path or secret-like diagnostic can therefore be persisted and exposed verbatim.

Strict gate: `tests/test_dev4_import_history_error_privacy.py`. It injects a synthetic parser exception containing a private Windows path and credential-like value and requires failed import history to retain useful failure evidence without retaining those private details. Product code unchanged.

## Locked defect classes

1. Import/ChessBase symlink-reparse indirection.
2. PGN unbounded full-text/resource boundary and no finite cap.
3. ChessBase private absolute paths in serialized evidence DTOs.
4. PGN expected-hash TOCTOU lost update.
5. PGN no-overwrite TOCTOU clobber.
6. PGN export path-indirection boundary.
7. ChessBase companion-directory I/O false-green.
8. Generic import batch RuntimeError abort.
9. ChessBase manifest verification I/O observability failure.
10. Shared import special-file/FIFO open-before-validation boundary.
11. Shared import fingerprint unstable-snapshot boundary.
12. ACSDB failed-import raw exception persistence/application exposure boundary.

## Other classifications

- QA EVIDENCE: PGN export failure recovery/temp cleanup/POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish path-bearing exceptions are sanitized.
- QA_OR_ENVIRONMENT_ONLY: current sandbox DNS prevented clean GitHub checkout.
- INCONCLUSIVE: exact QA CI until checks appear.
- INCONCLUSIVE: PGN directory crash/power-loss durability.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck PR #67 final exact head/CI, then continue generic import cancellation/encoding/truncation and ChessBase component snapshot/open/stat/hash observability. Trace further leakage only into concrete persisted/UI/report sinks. Stay out of Product-owner and Windows strict lanes.
