# DEV4 SESSION HANDOFF

SESSION: 20260822-1503 Full Product QA/security
STATUS: COMPLETE / SAFE OVERLAP

## Exact state basis

- DEV4 Product: `manual5/dev4-platform-security-packaging-20260821@a4209d005ea0a1476f8eafb4822f4d39ac50ee5a`.
- Accepted integration: `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`.
- DEV5 reconciliation PR #66 remains separate at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29` and was not mutated.
- DEV4 QA branch: `qa/dev4-chessbase-symlink-security-20260822`.
- New evidence commit: `97044de22bbab7098f0ba6a06fd9dfa5cd37562f` — `test(security): gate unstable ChessBase integrity snapshots`.
- QA PR #67 remains OPEN/DRAFT. Metadata commits follow the evidence commit; final exact branch head must be read live after synchronization.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## Evidence extension

`PROVEN_PRODUCT_DEFECT` class 11 is now independently proven on both provenance implementations: shared `acs.import_contract.fingerprint()` and ChessBase `acs.chessbase_integrity._fingerprint()`. The ChessBase path hashes in chunks without pre/post identity/stat stability validation, so an equal-size concurrent source mutation can still yield ordinary `SourceFileEvidence` rather than a fail-closed result.

Strict gate: `tests/test_dev4_chessbase_integrity_atomicity.py`. Product code unchanged.

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
11. Provenance unstable-snapshot boundary on both shared import and ChessBase integrity hashing.
12. ACSDB failed-import raw exception persistence/application exposure boundary.

## Other classifications

- QA EVIDENCE: PGN export failure recovery/temp cleanup/POSIX temp privacy.
- QA EVIDENCE: release-facing Stockfish path-bearing exceptions are sanitized.
- INCONCLUSIVE: exact QA CI until checks appear.
- INCONCLUSIVE: PGN directory crash/power-loss durability.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim.

## Next action

Recheck PR #67 final exact head/CI, then continue generic import cancellation/encoding/truncation and ChessBase component open/stat/hash observability. Trace further leakage only into concrete persisted/UI/report sinks. Stay out of Product-owner and Windows strict lanes.
