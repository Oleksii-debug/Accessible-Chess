# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read live DEV5 PR #66 / integration head before touching any Stage1 reconciliation. Do not compete with an IN_PROGRESS integration owner.
2. Recheck QA PR #67 exact head and Actions. Keep the symlink/reparse regression RED until Product code genuinely fails closed.
3. Audit generic external-import boundary beyond ChessBase: `import_contract`, `import_registry`, PGN open/save provenance and filesystem indirection. Prefer evidence/tests over Product fixes while another owner is active.
4. Build an evidence-backed ChessBase capability matrix for `.cbh`, `.cbg`, `.cbp`, `.cbt`, `.cbv`, `.cbf`, `.2cbh`, `.cbone`: SUPPORTED / PARTIAL / UNSUPPORTED / CORRUPT / BLOCKED. Recognition must never imply decoding support.
5. Audit bounded-read/resource-exhaustion handling for large/truncated external files and explicit unknown-version behavior. Preserve original sources read-only.
6. Review import report/provenance DTOs for source hash, adapter/version, warning/damage/loss state, duplicates, failed records and transaction result without absolute private-path leakage in user-facing surfaces.
7. Coordinate migration/rollback evidence only around DEV3-owned ACSDB storage; do not modify query/storage performance work while PR #65 or another DEV3 owner is IN_PROGRESS.
8. Continue Stage1 package/security reconciliation only when DEV5/Audit authorizes the relevant slice. Preserve accepted DEV1 board bridge semantics and keep `nuitka-compilation-report.xml` outside user ZIPs.

CLASSIFICATION RULES:
- `PROVEN_PRODUCT_DEFECT`: reproduced behavior contradicts active contract.
- `QA_OR_ENVIRONMENT_ONLY`: test/infrastructure failure without Product contract violation.
- `INCONCLUSIVE`: evidence insufficient or conflicting.
- `HUMAN_ONLY`: requires exact fresh Windows/NVDA/manual interaction evidence.

HARD INVARIANTS:
- Never weaken tests to get GREEN.
- Never force-push.
- Windows strict WIP=1; do not take it over.
- Do not claim Ctrl+A/Ctrl+C Product defects without proof.
- `NVDA_VERIFIED` stays `NO` until the user verifies the exact fresh candidate.
