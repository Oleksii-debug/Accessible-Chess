# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live DEV5/integration and QA PR #67 before any write; SAFE OVERLAP remains mandatory while Product owners are active.
2. Recheck final QA head and commit-associated Actions. Absence is `INCONCLUSIVE`, never GREEN.
3. Preserve all fourteen locked Product-defect classes; never weaken strict gates for GREEN.
4. Preserve PGN quality gates: invalid UTF-8 replacement and missing explicit game-termination markers must not be reported as record-level `FULL` merely because structural parsing succeeds.
5. Preserve ChessBase verification I/O observability and provenance atomicity gates.
6. Preserve the ACSDB import-history privacy gate and special-file fail-closed behavior.
7. Continue generic import evidence for explicit resource limits. Investigate duplicate-source and cancellation/recovery semantics only where a concrete contract/state transition can be proven; otherwise keep them `INCONCLUSIVE` rather than inventing requirements.
8. Trace `SourceFingerprint.path`, `BatchInspectionItem.path/error`, PGN and engine exceptions only into concrete persisted/UI/report sinks before promoting additional leakage findings.
9. Keep PGN parent-directory crash/power-loss durability `INCONCLUSIVE` without stronger evidence.
10. Re-enter Stage1/package Product work only through DEV5/Audit authorization; preserve accepted DEV1 board-bridge semantics and keep `nuitka-compilation-report.xml` out of user ZIPs.
11. Windows strict WIP=1; do not take it over. `NVDA_VERIFIED=NO` until exact fresh candidate human verification.

CURRENT LOCKED FINDINGS COUNT: 14 `PROVEN_PRODUCT_DEFECT` classes.

HARD INVARIANTS:
- Never weaken tests to get GREEN.
- Never force-push.
- Do not claim Ctrl+A/Ctrl+C Product defects without proof.
- Windows strict WIP=1.
- `NVDA_VERIFIED=NO`.
