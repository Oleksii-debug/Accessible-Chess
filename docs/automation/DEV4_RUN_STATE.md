# DEV4 RUN STATE

RUN_ID: 20260822-1700-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Product source: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration: `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684` (live compare IDENTICAL).
- DEV5 reconciliation PR #66 remains separate and OPEN/DRAFT at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; DEV4 did not mutate it.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New strict evidence commit: `96479111bd39a76bf7ebc5c40742f5b2275dcc29` — `test(qa): gate lossy PGN encoding quality`.
- Evidence-commit Actions: none observed -> `INCONCLUSIVE`, not GREEN.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New PROVEN_PRODUCT_DEFECT — lossy PGN decoding can remain FULL in record counts

`_read_text_snapshot()` decodes PGN with `errors="replace"` and `open_pgn()` records a global warning when replacement characters are present. `PgnFileImporter.inspect()` nevertheless derives each record quality only from `game.warnings`. A structurally parseable game whose source bytes required lossy UTF-8 replacement can therefore be recorded as `FULL`, making `ImportReport.counts` report full-quality games while its source text was altered during decoding.

Strict gate: `tests/test_dev4_pgn_encoding_quality.py`. It injects one invalid UTF-8 byte into an otherwise parseable PGN and requires record-level quality not to remain FULL. Product code intentionally unchanged.

## Locked PROVEN_PRODUCT_DEFECT findings

1. Import/ChessBase symlink-reparse indirection follows targets instead of failing closed.
2. PGN import lacks a bounded full-text/resource boundary and finite source cap.
3. ChessBase serialized probe/integrity/manifest DTOs expose absolute local paths.
4. PGN `expected_sha256` overwrite has a TOCTOU lost-update race.
5. PGN `overwrite=False` can clobber a destination created after preflight.
6. PGN export filesystem indirection is not fail-closed.
7. ChessBase companion-directory I/O failures collapse into ordinary no-companion evidence.
8. Generic import `inspect_batch()` aborts on importer `RuntimeError` instead of recording and continuing.
9. ChessBase verification I/O observability is not domain-safe across manifest and integrity verification.
10. Shared import fingerprinting can open FIFO/special files before fail-closed type validation.
11. Provenance hashing is not a stable snapshot on shared import and ChessBase integrity paths.
12. ACSDB failed-import history persists raw exception text and exposes it through `ImportHistoryService`.
13. Lossy invalid-UTF8 PGN decoding can still produce `FULL` record quality and misleading aggregate counts.

## Other classifications

- QA EVIDENCE: PGN export recovery/temp cleanup/POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish provider path errors are sanitized.
- INCONCLUSIVE: exact QA-head CI until checks appear.
- INCONCLUSIVE: PGN parent-directory crash/power-loss durability.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck final PR #67 head/CI. Continue generic import truncation/duplicate-source/cancellation-recovery and concrete persisted/UI/report error-sink tracing. Preserve all strict gates without weakening tests. Stay in SAFE OVERLAP and out of Windows strict/Product-owner lanes.
