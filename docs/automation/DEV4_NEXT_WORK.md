# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live DEV5 PR #66 and manual5 integration before any Stage1 reconciliation. Do not compete with an IN_PROGRESS integration owner.
2. Recheck QA PR #67 exact head and commit-associated Actions after the new PGN resource gate. Keep symlink/reparse and bounded-read assertions strict until real Product fixes exist.
3. Audit PGN/import resource boundaries further: explicit maximum source size, chunked decoding/parsing strategy, truncated input, duplicate sources, encoding abuse and cancellation/recovery. Prefer QA evidence/tests over Product fixes during active DEV5 work.
4. Trace absolute-path leakage end-to-end from `SourceFingerprint.path`, `BatchInspectionItem.error`, PGN exceptions and ChessBase evidence DTOs into actual UI/log/report surfaces. Classify only after proving visibility.
5. Build an evidence-backed ChessBase capability matrix for `.cbh`, `.cbg`, `.cbp`, `.cbt`, `.cbv`, `.cbf`, `.2cbh`, `.cbone`: SUPPORTED / PARTIAL / UNSUPPORTED / CORRUPT / BLOCKED. Suffix recognition must never imply decoder support.
6. Audit ChessBase bounded-read/resource-exhaustion and unknown-version handling beyond hashing; preserve original source read-only and do not invent proprietary semantics.
7. Review PGN export safety: path handling, overwrite/concurrency policy, temporary-file permissions/cleanup, atomic replacement, deterministic output and provenance without private-path leakage.
8. Coordinate migration/rollback evidence only at the DEV3 ACSDB boundary; do not modify query/storage performance work while another DEV3 Product owner is active.
9. Continue Stage1 package/security reconciliation only when DEV5/Audit authorizes the slice. Preserve accepted DEV1 board-bridge semantics and keep `nuitka-compilation-report.xml` outside user ZIPs.

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
