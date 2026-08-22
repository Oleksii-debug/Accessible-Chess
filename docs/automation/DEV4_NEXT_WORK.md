# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read Audit directive, PR #100 final exact head/Actions, QA PR #67, DEV5/integration state, Drive handoff and RUN_STATE before any mutation.
2. Exact-head CI absence is `INCONCLUSIVE`, never GREEN; consume exact failures if checks appear.
3. Preserve strict assertions; never weaken tests merely to pass.
4. Preserve atomic no-clobber semantics for `overwrite=False` and expected-hash recovery semantics for in-place writers at the final publication boundary.
5. Preserve new post-publication recovery invariant: if verification or rollback cannot complete after publication, the `.cas-*.bak` recovery snapshot must survive and contain recoverable pre-publication/newer writer bytes.
6. Preserve prior cleanup regressions: pre-publication expected-hash replace failure cleans `.tmp` + `.cas-*.bak` while preserving destination; no-clobber hard-link failure publishes nothing and cleans `.tmp`.
7. Inspect post-commit cleanup ambiguity next: CAS snapshot unlink failure after otherwise successful verified publication and no-clobber temp unlink failure after successful hard-link publication. Promote only if a deterministic contract violation is proven; do not churn Product for merely untidy but safe behavior.
8. Keep generic non-cooperative atomic-inode-swap CAS semantics `INCONCLUSIVE` without proof.
9. Keep directory crash/power-loss durability `INCONCLUSIVE` without a concrete contract/evidence.
10. Preserve ACSDB privacy, bounded PGN imports, fail-closed stable provenance, ChessBase privacy/observability and all previous publication repairs.
11. Missing-PGN-termination GameTree semantics remain outside DEV4 while DEV2 owns canonical GameTree behavior; retain strict QA evidence only.
12. Windows reparse/hard-link semantics require exact Windows evidence; do not infer from POSIX behavior.
13. Stay out of DEV5 integration, strict Windows workflows, Stage1 release ownership and `tools/qa` except DEV4-owned QA evidence maintenance.
14. Windows strict WIP=1. `NVDA_VERIFIED=NO` until exact fresh candidate human verification.

CURRENT DEV4 PRODUCT STATUS:
- newly proven post-publication recovery-snapshot deletion defect is repaired by `724cfd025c12e6800cd986b39237ce849542253a`;
- strict regression evidence is `d876d7661ce0ee0b141e9b9944965909967fea4c`;
- local test execution remains `QA_OR_ENVIRONMENT_ONLY` blocked by sandbox DNS;
- exact PR #100 CI remains `INCONCLUSIVE` until observable.
