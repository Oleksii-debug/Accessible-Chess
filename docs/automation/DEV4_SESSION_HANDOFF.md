# DEV4 SESSION HANDOFF

SESSION: 20260822-1300 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact state basis

- DEV4 Product: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration: `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation PR #66: `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`, OPEN/DRAFT.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New evidence commit: `cf61bbf18f352522ae3333deaff1e2dc353475b1` — `test(security): reject special-file import sources`.
- QA PR #67 remains OPEN/DRAFT/MERGEABLE. Metadata commits follow the evidence commit; canonical PR/Drive metadata records the final exact QA head.
- Previous exact-head Actions were absent; QA CI remains `INCONCLUSIVE`, not GREEN until observed.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New finding

`PROVEN_PRODUCT_DEFECT` — shared `fingerprint()` opens the submitted import path before validating that it is a regular file. A FIFO can block indefinitely waiting for a peer, and special/device-like paths can trigger unintended I/O. The external import boundary must reject non-regular files before opening payload bytes.

Strict deterministic gate: `tests/test_dev4_import_special_file_security.py`. It creates a POSIX FIFO and guards the payload-open boundary so the test itself cannot hang. Product code unchanged.

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

## Other classifications

- QA EVIDENCE: PGN export failure recovery/temp cleanup/POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish path-bearing exceptions are sanitized.
- INCONCLUSIVE: exact QA CI until checks appear.
- INCONCLUSIVE: PGN directory crash/power-loss durability.
- INCONCLUSIVE: generic path/error strings reaching UI/persisted sinks beyond proven ChessBase DTO leakage.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck PR #67 final head/CI, then continue generic import huge/truncated/encoding/cancellation evidence and ChessBase component open/stat/hash observability. Promote leakage only with concrete sink evidence. Stay out of Product-owner and Windows strict lanes.
