# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live DEV5 PR #66, manual5 integration and QA PR #67 before any new write. Do not compete with an IN_PROGRESS Product/integration owner.
2. Recheck QA PR #67 exact head and commit-associated Actions. Keep strict security assertions RED until genuine Product fixes exist; never weaken them for GREEN.
3. Preserve all six locked Product-defect classes plus positive QA guards for PGN export failure recovery and Stockfish error-path privacy.
4. Continue generic import resource limits: explicit maximum source size, chunked/streaming strategy, huge/truncated content, encoding abuse, duplicate sources, cancellation and recovery. Bounded hashing alone is not a bounded import.
5. Trace generic provenance/error exposure end-to-end from `SourceFingerprint.path`, `BatchInspectionItem.path/error`, PGN exceptions and engine/runtime exceptions into real persisted/UI/report surfaces. Promote only direct exposure.
6. Extend UCI/engine failure-surface QA where non-conflicting: startup/provider errors, timeout/retry failures and diagnostic logging must not leak private executable/user-profile paths into WebView/NVDA messages.
7. Keep PGN parent-directory durability INCONCLUSIVE unless a clear active contract plus reproducible crash/power-loss evidence justifies promotion.
8. Audit ChessBase bounded-read/resource-exhaustion and unknown-version handling beyond integrity hashing. Preserve source read-only and do not invent proprietary record semantics.
9. Maintain `DEV4_CHESSBASE_CAPABILITY_MATRIX.md` as evidence changes; suffix recognition must never be presented as decoder compatibility.
10. Re-enter Stage1 package/security reconciliation only when DEV5/Audit authorizes a slice. Preserve accepted DEV1 board-bridge semantics and keep `nuitka-compilation-report.xml` outside user ZIPs.

CURRENT LOCKED FINDINGS:
- PROVEN_PRODUCT_DEFECT: external import/ChessBase symlink-reparse boundary follows indirection instead of failing closed.
- PROVEN_PRODUCT_DEFECT: PGN import performs an unbounded full-text read after bounded hashing.
- PROVEN_PRODUCT_DEFECT: serialized ChessBase probe/integrity/manifest report DTOs expose absolute local paths.
- PROVEN_PRODUCT_DEFECT: PGN expected_sha256 optimistic overwrite has a TOCTOU lost-update window.
- PROVEN_PRODUCT_DEFECT: PGN overwrite=False can clobber a destination created after preflight.
- PROVEN_PRODUCT_DEFECT: PGN export filesystem-indirection boundary is not fail-closed; strict coverage includes direct parent, deeper ancestor and destination-file symlinks.
- QA EVIDENCE: PGN export recovery guard locks destination preservation/temp cleanup on injected `os.replace`/`os.fsync` failures plus POSIX private temp-mode expectations.
- QA EVIDENCE: release-facing engine-game startup sanitizes provider exceptions containing synthetic private Stockfish paths before WebView/NVDA output; gate `tests/test_dev4_engine_error_path_privacy.py`.
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
