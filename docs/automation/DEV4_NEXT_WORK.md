# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live DEV5 PR #66, manual5 integration and QA PR #67 before any new write. Do not compete with an IN_PROGRESS Product/integration owner.
2. Recheck QA PR #67 exact head and commit-associated Actions. Keep all strict security assertions RED until genuine Product fixes exist; never weaken them for GREEN.
3. Continue PGN export safety after the proven optimistic-concurrency race: parent/destination symlink or reparse behavior, temp-file permissions and cleanup, `os.replace`/`fsync` failure recovery, directory durability, deterministic serialization, overwrite policy and user-visible path/error leakage.
4. Preserve the new strict gate `tests/test_dev4_pgn_export_concurrency_security.py`: `expected_sha256` must still protect against a writer that updates the destination after preflight but before atomic commit.
5. Continue generic import resource limits: explicit maximum source size, chunked/streaming strategy, huge/truncated content, encoding abuse, duplicate sources, cancellation and recovery. Bounded hashing alone is not a bounded import.
6. Trace generic provenance/error path exposure end-to-end from `SourceFingerprint.path`, `BatchInspectionItem.path/error`, PGN exceptions and ChessBase evidence DTOs into persisted/UI/report surfaces. ChessBase report DTO leakage is already PROVEN; classify other surfaces only with direct evidence.
7. Audit ChessBase bounded-read/resource-exhaustion and unknown-version handling beyond integrity hashing. Preserve source read-only and do not invent proprietary record semantics.
8. Maintain `DEV4_CHESSBASE_CAPABILITY_MATRIX.md` as evidence changes; suffix recognition must never be presented as decoder compatibility.
9. Coordinate migration/rollback evidence only at the DEV3 ACSDB boundary; do not modify active ACSDB query/storage performance work.
10. Re-enter Stage1 package/security reconciliation only when DEV5/Audit authorizes a slice. Preserve accepted DEV1 board-bridge semantics and keep `nuitka-compilation-report.xml` outside user ZIPs.

CURRENT LOCKED FINDINGS:
- PROVEN_PRODUCT_DEFECT: external import/ChessBase symlink-reparse boundary follows indirection instead of failing closed.
- PROVEN_PRODUCT_DEFECT: PGN import performs an unbounded full-text read after bounded hashing.
- PROVEN_PRODUCT_DEFECT: serialized ChessBase probe/integrity/manifest report DTOs expose absolute local paths.
- PROVEN_PRODUCT_DEFECT: PGN optimistic overwrite has a TOCTOU window; a newer destination write after preflight can be silently lost at unconditional `os.replace`.
- PROVEN_PRODUCT_INTEGRATION_RISK: naive DEV4 board-action overwrite can regress accepted DEV1 semantics.
- PROVEN_RELEASE_PIPELINE_BLOCKER: Nuitka compiler report must not ship in user candidate.
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
