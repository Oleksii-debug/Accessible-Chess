# DEV4 RUN STATE

RUN_ID: 20260822-1800-full-product-qa
STATUS: COMPLETE
MODE: SAFE_OVERLAP_QA_EVIDENCE
ROLE: DEV4 independent QA/evidence/security

## Live snapshot

- DEV4 Product source: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration remains `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684` from the current canonical lane state.
- DEV5 reconciliation PR #66 remains separate and OPEN/DRAFT at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; DEV4 did not mutate it.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New strict evidence commit: `706babfe7b2ad894cf8552a4b109899784f48a23` — `test(qa): gate truncated PGN quality false-green`.
- Evidence-commit Actions: none observed -> `INCONCLUSIVE`, not GREEN.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New PROVEN_PRODUCT_DEFECT — abruptly terminated PGN can be counted FULL

`gametree.parse_games()` accepts movetext that ends after a move without a game-termination marker. `_parse_line()` produces no warning, `parse_games()` silently substitutes `header_result or "*"`, and `PgnFileImporter.inspect()` therefore assigns record-level `FULL` when `game.warnings` is empty. A truncated PGN can consequently increment `ImportReport.counts['full']` instead of warning/partial/damaged quality.

The PGN specification requires each movetext section to contain exactly one game-termination marker as its last element, so silent synthesis of `*` must not be represented as full-fidelity evidence.

Strict gate: `tests/test_dev4_pgn_truncation_quality.py`. It supplies a PGN ending at `2. Nf3` with no termination marker and requires record quality not to remain FULL. Product code intentionally unchanged.

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
14. A PGN with no explicit game-termination marker can be silently completed with `*` and counted as `FULL` instead of being marked recovered/truncated.

## Other classifications

- QA EVIDENCE: PGN export recovery/temp cleanup/POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish provider path errors are sanitized.
- INCONCLUSIVE: exact QA-head CI until checks appear.
- INCONCLUSIVE: PGN parent-directory crash/power-loss durability.
- INCONCLUSIVE: duplicate-source semantics and cancellation contract until a concrete product requirement or bad state transition is proven.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck final PR #67 head/CI. Continue duplicate-source/cancellation-recovery only where a concrete contract exists, plus explicit resource limits and concrete persisted/UI/report sink tracing. Preserve all strict gates without weakening tests. Stay in SAFE OVERLAP and out of Windows strict/Product-owner lanes.
