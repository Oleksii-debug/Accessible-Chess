# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read Audit directive, PR #100 exact head/Actions, QA PR #67 evidence, DEV5/integration state, Drive handoff and RUN_STATE before mutation.
2. Exact-head CI absence is `INCONCLUSIVE`, never GREEN; consume exact failures if checks appear.
3. Preserve all strict QA gates; never weaken tests merely to pass.
4. Remaining highest DEV4-owned repair: PGN publication concurrency. `expected_sha256` must behave as an actual compare-and-swap at commit, and `overwrite=False` must provide actual atomic no-clobber semantics.
5. Do not treat a second preflight `exists()`/hash check as a complete repair; the race must be closed at publication boundary.
6. Preserve ACSDB error privacy repair: persisted/application-facing history must not contain raw workstation paths, tokens or provider exception internals.
7. Preserve PGN export lexical path-indirection checks across ancestors/destination and revalidate after directory creation/before commit.
8. Keep missing-PGN-termination GameTree semantics outside DEV4 while DEV2 owns canonical GameTree/domain behavior; retain strict QA evidence.
9. Recheck Windows reparse semantics only with exact Windows evidence; do not claim proof from POSIX-only behavior.
10. Stay out of `tools/qa`, strict Windows workflows, Stage1 release lineage and DEV5 integration ownership.
11. Windows strict WIP=1. `NVDA_VERIFIED=NO` until exact fresh candidate human verification.

CURRENT PRODUCT REPAIRS IN PR #100 now also include:
- ACSDB persisted failed-import error redaction while preserving exception re-raise;
- PGN export ancestor/destination symlink-reparse fail-closed validation.

CURRENT UNREPAIRED PROVEN DEV4 DEFECTS:
- PGN expected-hash publication race;
- PGN no-overwrite publication race.

INCONCLUSIVE: exact PR #100 CI until observed; Windows-specific reparse behavior until executed on Windows.
HUMAN_ONLY: exact fresh Windows/NVDA usability.
