# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live DEV5/integration and QA PR #67 before any write; SAFE OVERLAP remains mandatory while Product owners are active.
2. Recheck QA head and commit-associated Actions. Absence is `INCONCLUSIVE`, never GREEN.
3. Preserve all eleven locked Product-defect classes; never weaken strict gates for GREEN.
4. Preserve special-file fail-closed and unstable-fingerprint gates: external provenance must reject non-regular sources before open and reject mutation during hashing.
5. Continue generic import limits: huge/truncated inputs, encoding abuse, duplicate-source behavior, cancellation and recovery.
6. Preserve ChessBase companion-directory and manifest verification I/O observability; extend component snapshot/open/stat/hash failure tests without inventing proprietary decoder semantics.
7. Trace `SourceFingerprint.path`, `BatchInspectionItem.path/error`, PGN and engine exceptions only into concrete persisted/UI/report sinks before promoting leakage findings.
8. Keep PGN parent-directory crash/power-loss durability `INCONCLUSIVE` without stronger evidence.
9. Preserve accepted DEV1 board-bridge semantics; re-enter Stage1/package Product work only through DEV5/Audit authorization.
10. Keep `nuitka-compilation-report.xml` out of user ZIPs.
11. Windows strict WIP=1; do not take it over. `NVDA_VERIFIED=NO` until exact fresh candidate human verification.

CURRENT LOCKED FINDINGS:
- PROVEN_PRODUCT_DEFECT: import/ChessBase symlink-reparse boundary follows indirection.
- PROVEN_PRODUCT_DEFECT: PGN import lacks bounded full-text/resource boundary and finite cap.
- PROVEN_PRODUCT_DEFECT: ChessBase serialized DTOs expose absolute local paths.
- PROVEN_PRODUCT_DEFECT: PGN expected-hash TOCTOU lost update.
- PROVEN_PRODUCT_DEFECT: PGN no-overwrite TOCTOU clobber.
- PROVEN_PRODUCT_DEFECT: PGN export path indirection is not fail-closed.
- PROVEN_PRODUCT_DEFECT: ChessBase companion enumeration I/O false-green.
- PROVEN_PRODUCT_DEFECT: generic import batch aborts on importer RuntimeError.
- PROVEN_PRODUCT_DEFECT: ChessBase manifest verification propagates hash/open I/O failure instead of structured failed verification.
- PROVEN_PRODUCT_DEFECT: shared import fingerprinting can open FIFO/special files before regular-file validation.
- PROVEN_PRODUCT_DEFECT: shared import fingerprinting does not reject a source that mutates during hashing.
- QA EVIDENCE: PGN export failure recovery/temp cleanup/POSIX temp privacy.
- QA EVIDENCE: release-facing engine errors redact private Stockfish paths.
- INCONCLUSIVE: exact QA-head CI until observed.
- HUMAN_ONLY: exact fresh Windows/NVDA usability.

HARD INVARIANTS:
- Never weaken tests to get GREEN.
- Never force-push.
- Do not claim Ctrl+A/Ctrl+C Product defects without proof.
- Windows strict WIP=1.
- `NVDA_VERIFIED=NO`.
