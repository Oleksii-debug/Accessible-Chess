# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read Audit directive, PR #100 exact head/Actions, QA PR #67 evidence, DEV5/integration state, Drive handoff and RUN_STATE before any mutation.
2. Exact-head CI absence is `INCONCLUSIVE`, never GREEN; consume exact failures if checks appear.
3. Preserve all strict QA gates; never weaken tests merely to pass.
4. Preserve atomic no-clobber semantics for `overwrite=False`: same-directory publication must fail with `FileExistsError` if another writer wins destination creation.
5. Preserve expected-hash recovery semantics: recheck expected digest at commit and preserve a competing in-place writer detected in the final publication window.
6. Preserve publication cleanup regressions: expected-hash replace failure must leave the old destination intact and remove `.tmp` plus `.cas-*.bak`; no-clobber hard-link failure must publish nothing and remove `.tmp`.
7. Keep the temp-file POSIX privacy gate attached to the actual `os.link` no-clobber publication primitive. The assertion remains zero group/world permission bits before commit.
8. Do not overclaim generic filesystem CAS. A non-cooperative external atomic inode swap in the narrow replacement window remains `INCONCLUSIVE` unless exact evidence proves behavior.
9. Inspect post-publication verification/rollback failure behavior and directory durability only where a concrete product contract and deterministic evidence exist; otherwise keep `INCONCLUSIVE`.
10. Preserve ACSDB error privacy, bounded PGN imports, stable fail-closed provenance and ChessBase observability/privacy repairs.
11. Keep missing-PGN-termination GameTree semantics outside DEV4 while DEV2 owns canonical GameTree/domain behavior; retain strict QA evidence.
12. Recheck Windows reparse and hard-link semantics only with exact Windows evidence; do not infer them from POSIX-only behavior.
13. Stay out of `tools/qa`, strict Windows workflows, Stage1 release lineage and DEV5 integration ownership except DEV4-owned QA evidence maintenance.
14. Windows strict WIP=1. `NVDA_VERIFIED=NO` until exact fresh candidate human verification.

CURRENT DEV4 PRODUCT STATUS: no newly proven unrepaired DEV4-owned strict defect in this cleanup wave.
QA_OR_ENVIRONMENT_ONLY: stale temp-permission instrumentation repaired on Product and QA branches without weakening the assertion.
QA EVIDENCE: publication failure cleanup expanded for CAS backup/temp and no-clobber hard-link failure.
INCONCLUSIVE: exact PR #100 CI; generic non-cooperative atomic-inode-swap CAS; Windows-specific reparse/hard-link behavior; directory crash/power-loss durability without stronger proof.
HUMAN_ONLY: exact fresh Windows/NVDA usability.
