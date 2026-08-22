# DEV4 SESSION HANDOFF

SESSION: 20260822-1700 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact state basis

- DEV4 Product: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration: `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684` (live IDENTICAL at run start).
- DEV5 reconciliation PR #66 remains separate at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29` and was not mutated.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New evidence commit: `96479111bd39a76bf7ebc5c40742f5b2275dcc29` — `test(qa): gate lossy PGN encoding quality`.
- Evidence-commit Actions were absent: `INCONCLUSIVE`, not GREEN.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New finding

`PROVEN_PRODUCT_DEFECT` — PGN lossy UTF-8 replacement can remain record-level FULL. `_read_text_snapshot()` uses replacement decoding and `open_pgn()` emits a global warning, but `PgnFileImporter.inspect()` assigns record quality only from `game.warnings`. A parseable game derived from altered replacement-decoded text can therefore increment `report.counts['full']` rather than warning/partial/damaged counts.

Strict gate: `tests/test_dev4_pgn_encoding_quality.py`. Product code unchanged.

## Locked defect classes

1. Import/ChessBase symlink-reparse indirection.
2. PGN unbounded full-text/resource boundary and no finite cap.
3. ChessBase private absolute paths in serialized evidence DTOs.
4. PGN expected-hash TOCTOU lost update.
5. PGN no-overwrite TOCTOU clobber.
6. PGN export path-indirection boundary.
7. ChessBase companion-directory I/O false-green.
8. Generic import batch RuntimeError abort.
9. ChessBase verification I/O observability failure.
10. Shared import special-file/FIFO open-before-validation boundary.
11. Provenance unstable-snapshot boundary on shared import and ChessBase integrity hashing.
12. ACSDB failed-import raw exception persistence/application exposure.
13. Lossy PGN encoding can be counted as FULL record quality.

## Other classifications

- QA EVIDENCE: PGN export failure recovery/temp cleanup/POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish path-bearing exceptions are sanitized.
- INCONCLUSIVE: exact QA CI until checks appear.
- INCONCLUSIVE: PGN directory crash/power-loss durability.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck PR #67 exact head/CI, then continue generic import truncation/duplicate-source/cancellation-recovery and concrete persisted/UI/report sink tracing. Stay out of Product-owner and Windows strict lanes.
