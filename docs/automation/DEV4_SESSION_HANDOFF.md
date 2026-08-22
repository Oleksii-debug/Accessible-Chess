# DEV4 SESSION HANDOFF

SESSION: 20260822-1400 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact state basis

- DEV4 Product: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration: `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New evidence commit: `55e0ab813d07ed6ea9e7b350a9cc899b5616a15c` — `test(security): gate unstable import fingerprints`.
- QA PR #67 remains OPEN/DRAFT/MERGEABLE. Metadata commits follow the evidence commit; final exact branch head must be read live after metadata synchronization.
- Exact QA CI remains `INCONCLUSIVE` until commit-associated Actions are observed.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New finding

`PROVEN_PRODUCT_DEFECT` — shared `fingerprint()` can return normal provenance when the source changes during hashing. It hashes the stream and records a later stat without proving a stable source snapshot; same-size concurrent mutation can therefore produce stale or mixed evidence instead of a fail-closed result.

Strict deterministic gate: `tests/test_dev4_import_fingerprint_atomicity.py`. It performs an equal-size mutation immediately after the first digest update and requires the fingerprint operation to reject the unstable snapshot. Product code unchanged.

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

## Other classifications

- QA EVIDENCE: PGN export failure recovery/temp cleanup/POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish path-bearing exceptions are sanitized.
- INCONCLUSIVE: exact QA CI until checks appear.
- INCONCLUSIVE: PGN directory crash/power-loss durability.
- INCONCLUSIVE: generic path/error strings reaching UI/persisted sinks beyond proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck PR #67 exact head/CI, then continue generic import cancellation/encoding/truncation and ChessBase component snapshot/open/stat/hash observability. Promote leakage only with concrete sink evidence. Stay out of Product-owner and Windows strict lanes.
