# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read Audit directive, PR #100 exact head/Actions, QA PR #67 evidence, DEV5/integration state, Drive handoff and RUN_STATE before any mutation.
2. Exact-head CI absence is `INCONCLUSIVE`, never GREEN; consume exact failures if checks appear.
3. Preserve all strict QA gates; never weaken tests merely to pass.
4. Preserve atomic no-clobber semantics for `overwrite=False`: same-directory publication must fail with `FileExistsError` if another writer wins destination creation.
5. Preserve expected-hash recovery semantics: recheck expected digest at commit and preserve a competing in-place writer detected in the final publication window.
6. Do not overclaim generic filesystem CAS. A non-cooperative external atomic inode swap in the narrow replacement window remains `INCONCLUSIVE` unless exact evidence proves behavior.
7. Inspect publication cleanup/durability interactions: temp/backup cleanup, fsync failure recovery, hard-link support/error mapping, destination/ancestor indirection revalidation and fingerprint return path.
8. Preserve ACSDB error privacy, bounded PGN imports, stable fail-closed provenance and ChessBase observability/privacy repairs.
9. Keep missing-PGN-termination GameTree semantics outside DEV4 while DEV2 owns canonical GameTree/domain behavior; retain strict QA evidence.
10. Recheck Windows reparse and hard-link semantics only with exact Windows evidence; do not infer them from POSIX-only behavior.
11. Stay out of `tools/qa`, strict Windows workflows, Stage1 release lineage and DEV5 integration ownership except DEV4-owned QA evidence maintenance.
12. Windows strict WIP=1. `NVDA_VERIFIED=NO` until exact fresh candidate human verification.

CURRENT PROVEN DEV4 PUBLICATION RACE TESTS: Product repair implemented in PR #100; no known unrepaired DEV4-owned strict defect from those two tests at this checkpoint.
INCONCLUSIVE: exact PR #100 CI; generic non-cooperative atomic-inode-swap CAS; Windows-specific reparse/hard-link behavior.
HUMAN_ONLY: exact fresh Windows/NVDA usability.