# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live DEV5/integration and QA PR #67 before any write; SAFE OVERLAP remains mandatory while Product owners are active.
2. Recheck QA head and commit-associated Actions. Absence is `INCONCLUSIVE`, never GREEN.
3. Preserve all twelve locked Product-defect classes; never weaken strict gates for GREEN.
4. Preserve provenance atomicity on both paths now covered by strict gates: shared `import_contract.fingerprint()` and ChessBase `chessbase_integrity._fingerprint()` must reject in-flight source mutation instead of returning normal evidence.
5. Preserve the concrete ACSDB import-history privacy gate: raw workstation paths, tokens, provider details, or other private exception internals must not be persisted/exposed verbatim.
6. Continue generic import limits: huge/truncated inputs, encoding abuse, duplicate-source behavior, cancellation and recovery.
7. Preserve special-file fail-closed behavior: external provenance must reject non-regular sources before open.
8. Preserve ChessBase companion-directory and manifest verification I/O observability; extend component open/stat/hash failure tests without inventing proprietary decoder semantics.
9. Trace `SourceFingerprint.path`, `BatchInspectionItem.path/error`, PGN and engine exceptions only into concrete persisted/UI/report sinks before promoting additional leakage findings.
10. Keep PGN parent-directory crash/power-loss durability `INCONCLUSIVE` without stronger evidence.
11. Re-enter Stage1/package Product work only through DEV5/Audit authorization; preserve accepted DEV1 board-bridge semantics and keep `nuitka-compilation-report.xml` out of user ZIPs.
12. Windows strict WIP=1; do not take it over. `NVDA_VERIFIED=NO` until exact fresh candidate human verification.

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
- PROVEN_PRODUCT_DEFECT: provenance hashing accepts in-flight same-size mutation in both shared import and ChessBase integrity snapshot paths.
- PROVEN_PRODUCT_DEFECT: ACSDB import attempts persist raw parser/provider exception text and `ImportHistoryService` exposes it application-side.
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
