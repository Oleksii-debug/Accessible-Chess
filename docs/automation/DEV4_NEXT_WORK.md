# DEV4 NEXT WORK

NEXT_ACTION_ORDER:

1. Re-read 19:00 Audit directive, PR #100 exact head/Actions, PR #67 strict evidence, DEV5/integration state, canonical Drive handoff and RUN_STATE before any Product mutation.
2. If PR #100 obtains exact-head CI, consume failures as technical truth. Absence remains `INCONCLUSIVE`, never GREEN.
3. Preserve all strict QA tests. Do not weaken evidence to make the Product branch pass.
4. Highest next DEV4-owned repair: sanitize ACSDB failed-import persistence/application reporting so private workstation paths, tokens and provider internals are not stored/exposed verbatim while useful failure classification remains.
5. Then repair PGN export destination/ancestor symlink-reparse indirection fail-closed.
6. Then design and repair PGN publication concurrency: `expected_sha256` lost-update and `overwrite=False` no-clobber must be enforced at the actual commit boundary with recoverable atomic semantics, not a preflight-only recheck.
7. Keep missing-PGN-termination GameTree semantics out of DEV4 while DEV2 owns canonical GameTree/domain behavior; retain the strict QA finding for integration review.
8. Recheck import source hardening across POSIX and Windows reparse semantics; do not claim Windows proof without exact Windows execution.
9. Keep ChessBase recognition separate from proprietary decoder claims. No decoder compatibility inflation.
10. Stay out of `tools/qa`, strict Windows workflows, Stage1 release lineage and DEV5 integration ownership.
11. Windows strict WIP=1. `NVDA_VERIFIED=NO` until Oleksii verifies the exact fresh candidate.

CURRENT PRODUCT REPAIRS IN PR #100:
- fail-closed regular-file/stable fingerprint boundary;
- finite bounded PGN reads;
- lossy UTF-8 record-quality downgrade;
- batch RuntimeError isolation;
- ChessBase report path privacy;
- companion I/O observability;
- stable/domain-safe integrity verification;
- manifest symlink/I/O/privacy hardening.

CURRENT UNREPAIRED PROVEN DEV4 DEFECTS:
- PGN expected-hash publication race;
- PGN no-overwrite publication race;
- PGN export path indirection;
- ACSDB raw failed-import error persistence/application exposure.

INCONCLUSIVE: exact PR #100 CI until observed; Windows-specific reparse behavior until executed on Windows.
HUMAN_ONLY: exact fresh Windows/NVDA usability.
