# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live DEV5 canonical handoff, DEV1 active state, DEV2/DEV3 exact packages, manual5 integration and QA PR #67 before any new write. SAFE OVERLAP remains mandatory while DEV1 is IN_PROGRESS.
2. Recheck QA PR #67 exact head and commit-associated Actions. Keep strict security assertions RED until genuine Product fixes exist; never weaken them for GREEN.
3. Preserve all eight locked Product-defect classes plus positive QA guards for PGN export failure recovery and Stockfish error-path privacy.
4. Preserve the strengthened PGN resource gate in `tests/test_dev4_pgn_resource_security.py`: untrusted PGN must use bounded reads and must have a finite source-size rejection before payload open. The test intentionally does not prescribe a production threshold.
5. Preserve `tests/test_dev4_import_batch_adapter_failure.py`: importer/decoder/provider runtime failure must be recorded per source and must not hide later batch results.
6. Continue generic import resource limits beyond PGN: huge/truncated inputs, encoding abuse, duplicate sources, cancellation and recovery. Bounded hashing alone is not a bounded import.
7. Extend ChessBase evidence observability: companion-directory enumeration, component open/stat/hash failures and unreadable/inaccessible evidence must remain distinguishable from verified absence.
8. Trace generic provenance/error exposure end-to-end from `SourceFingerprint.path`, `BatchInspectionItem.path/error`, PGN exceptions and engine/runtime exceptions into real persisted/UI/report surfaces. Promote only direct exposure.
9. Extend UCI/engine failure-surface QA only where non-conflicting and user-facing.
10. Keep PGN parent-directory durability INCONCLUSIVE unless stronger crash/power-loss evidence exists.
11. Maintain `DEV4_CHESSBASE_CAPABILITY_MATRIX.md`; suffix recognition must never be presented as decoder compatibility.
12. Re-enter Stage1/package Product work only when DEV5/Audit authorizes a slice. Preserve accepted DEV1 board-bridge semantics and keep `nuitka-compilation-report.xml` outside user ZIPs.

CURRENT LOCKED FINDINGS:
- PROVEN_PRODUCT_DEFECT: external import/ChessBase symlink-reparse boundary follows indirection instead of failing closed.
- PROVEN_PRODUCT_DEFECT: PGN import has no bounded full-text/resource boundary: unbounded read plus no finite source-size rejection before payload open.
- PROVEN_PRODUCT_DEFECT: serialized ChessBase probe/integrity/manifest report DTOs expose absolute local paths.
- PROVEN_PRODUCT_DEFECT: PGN expected_sha256 optimistic overwrite has a TOCTOU lost-update window.
- PROVEN_PRODUCT_DEFECT: PGN overwrite=False can clobber a destination created after preflight.
- PROVEN_PRODUCT_DEFECT: PGN export filesystem-indirection boundary is not fail-closed.
- PROVEN_PRODUCT_DEFECT: ChessBase CBH companion directory I/O failures are collapsed into ordinary no-companion evidence.
- PROVEN_PRODUCT_DEFECT: generic import `inspect_batch()` aborts on importer `RuntimeError` instead of recording failure and continuing later sources.
- QA EVIDENCE: PGN export recovery guard locks destination preservation/temp cleanup on injected `os.replace`/`os.fsync` failures plus POSIX private temp-mode expectations.
- QA EVIDENCE: release-facing engine-game startup sanitizes provider exceptions containing synthetic private Stockfish paths before WebView/NVDA output.
- PROVEN_PRODUCT_INTEGRATION_RISK: naive DEV4 board-action overwrite can regress accepted DEV1 semantics.
- PROVEN_RELEASE_PIPELINE_BLOCKER: Nuitka compiler report must not ship in user candidate.
- INCONCLUSIVE: QA PR #67 exact-head Actions until observed.
- HUMAN_ONLY: exact fresh Windows/NVDA usability; `NVDA_VERIFIED=NO`.

CLASSIFICATION RULES:
- `PROVEN_PRODUCT_DEFECT`: live behavior/code path directly contradicts an active contract and is independently reproducible or locked by a strict regression.
- `QA_OR_ENVIRONMENT_ONLY`: test/infrastructure failure without Product contract violation.
- `INCONCLUSIVE`: evidence insufficient, conflicting, or observability missing.
- `HUMAN_ONLY`: requires exact fresh Windows/NVDA/manual interaction evidence.

HARD INVARIANTS:
- Never weaken tests to get GREEN.
- Never force-push.
- Windows strict WIP=1; do not take it over.
- Do not claim Ctrl+A/Ctrl+C Product defects without proof.
- `NVDA_VERIFIED` stays `NO` until the user verifies the exact fresh candidate.
