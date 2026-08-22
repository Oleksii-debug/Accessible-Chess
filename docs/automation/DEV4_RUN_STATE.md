# DEV4 RUN STATE

RUN_ID: 20260822-2229-full-product-repair
STATUS: COMPLETE_WITH_CI_UNOBSERVED
MODE: DEV4_PRODUCT_REPAIR
ROLE: DEV4 Product Developer — import/PGN/ChessBase/security ownership
DIRECTIVE: AUDIT-20260822-1900-01 + DEV5 0022 read as non-competing coordination context

## Live state

- Product branch: `full5/dev4-import-security-repair-20260822`.
- Product PR #100 remains OPEN/DRAFT/MERGEABLE against `manual5/dev4-platform-security-packaging-20260821`.
- Run-start Product head: `f44113ac3c7783aca761c0a7e9044a6cac334cb3`.
- New strict regression commit: `d876d7661ce0ee0b141e9b9944965909967fea4c` — gates post-publication rollback/verification failures.
- New Product repair commit: `724cfd025c12e6800cd986b39237ce849542253a` — preserves CAS recovery snapshots when post-publication verification or rollback cannot complete safely.
- Accepted Stage1 integration remains `manual5/integration-20260821@0fa442330bc2bb03636ff9297512da4c29e38684`; live compare remained IDENTICAL and it was not mutated.
- DEV5 reconciliation PR #66 remains separate at `abff45ebcc4b5af2a85ab0c456b025b5098c6e29`; not mutated.
- QA PR #67 remains separate; strict historical assertions were not weakened.
- Exact Product-head Actions/status contexts remain absent: `INCONCLUSIVE`, not GREEN.
- Local clean-checkout/focused execution is blocked because this execution sandbox cannot resolve `github.com`: `QA_OR_ENVIRONMENT_ONLY`, not Product evidence.
- Windows strict WIP=1 untouched. `NVDA_VERIFIED=NO`.

## New PROVEN_PRODUCT_DEFECT — post-publication recovery evidence could be destroyed on rollback/verification failure

The repaired expected-hash publication path intentionally keeps a hard-link snapshot of the pre-publication inode so a writer racing in-place at the final replacement boundary can be restored. Before this run, once `os.replace(tmp, destination)` had published our file, two failure paths were unsafe:

1. if the post-publication snapshot digest check failed with an I/O/validation error, the `finally` block still unlinked the recovery snapshot;
2. if a concurrent writer was detected but `os.replace(snapshot, destination)` rollback itself failed, the same `finally` block unlinked the snapshot after the failed rollback.

In the rollback case this can destroy the only recoverable copy of the concurrent writer's newer bytes while leaving our stale publication at the destination. This is a deterministic data-loss/recovery defect in DEV4-owned Product code.

Strict regressions in `tests/test_dev4_pgn_export_failure_recovery.py` now require:
- failed rollback preserves exactly one `.cas-*.bak` containing the concurrent writer bytes;
- post-publication verification failure preserves exactly one `.cas-*.bak` containing the original pre-publication bytes;
- `.tmp` debris is still removed.

Product repair in `acs/pgn_service.py` sets an explicit preserve-snapshot state after publication when verification cannot be trusted or rollback fails, maps those failures to `PgnFileError`, and skips destructive CAS cleanup in those states. Normal pre-publication failures and successful verified publication still clean snapshots as before.

## Classification

- `PROVEN_PRODUCT_DEFECT`: post-publication verification/rollback failure could delete recoverable CAS evidence after publication.
- `REPAIRED_IN_PRODUCT`: `724cfd025c12e6800cd986b39237ce849542253a`.
- `STRICT_REGRESSION_EVIDENCE`: `d876d7661ce0ee0b141e9b9944965909967fea4c`.
- `QA_OR_ENVIRONMENT_ONLY`: local checkout/test execution blocked by sandbox DNS failure.
- `INCONCLUSIVE`: exact PR #100 CI until commit-associated checks appear.
- `INCONCLUSIVE`: generic non-cooperative external atomic inode replacement in the narrow CAS window.
- `INCONCLUSIVE`: Windows-specific reparse/hard-link behavior until exact Windows execution.
- `INCONCLUSIVE`: directory crash/power-loss durability without stronger contract/evidence.
- `HUMAN_ONLY`: exact fresh Windows/NVDA usability.
- No Ctrl+A/Ctrl+C Product defect claim. `NVDA_VERIFIED=NO`.

## Next action

Read PR #100 final metadata head/CI after handoff synchronization. Next safe DEV4 slice is post-commit cleanup ambiguity (CAS snapshot unlink and no-clobber temp unlink failures) only if a deterministic contract violation is proven, plus exact CI failure consumption if checks appear. Preserve all prior repairs and stay out of DEV5 integration, strict Windows QA, Stage1 release and DEV2 GameTree ownership.
