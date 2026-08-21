# AUTO-CHESS DEV3 run state

STATUS: COMPLETE FOR PGN FILE-PUBLICATION LOST-UPDATE SLICE / FULL PRODUCT MISSION PARTIAL
BRANCH: `auto/dev3-acsdb-stable-paging-20260821`
PR: #65
DIRECTIVE: Full Product DEV3 / engine-analysis + ACSDB-Library-Search-import-export safety

Latest verified executable package head before documentation synchronization: `7c1c0b8092fc487e49d9a654f0f847f6035bedb1`.
Exact CI run: `32535629207`.
Exact CI job: `96935870586` — SUCCESS.
The PR workflow checked out merge ref `acdc7e8754d150e3ddce367f9ba02831f4e5a7ce` for head `7c1c0b8...` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: `2.336.0`; image `ubuntu-24.04@20260816.277.1`; Python `3.12.14`.

Product defect closed:
- before this slice, `save_pgn_atomic(..., overwrite=False)` checked that the destination did not exist, wrote/fsynced a peer temp file, then unconditionally used `os.replace()`;
- a second writer could create the destination after the check and before replace, causing a silent lost update despite the no-overwrite contract;
- no-overwrite publication now uses an atomic same-directory create-if-absent operation and fails if a competing destination already exists;
- overwrite=True retains explicit atomic replacement semantics;
- `overwrite` rejects coercive non-boolean values;
- deterministic regression forces the competing-creator window and proves competitor content is preserved plus temporary-file cleanup.

Exact executable evidence on `7c1c0b8...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 ACSDB suite: 36/36 PASS;
- full unittest discovery: 573/573 PASS;
- full pytest: 651 passed + 545 subtests passed;
- new PGN race and strict-overwrite tests PASS;
- no weakened or skipped tests for GREEN.

SAFE OVERLAP / ownership:
- no canonical GameTree/chess-rule source changed; DEV2 remains owner there;
- no DEV1 presentation/UI code changed;
- DEV4 QA PR #67 security findings were not taken over or altered;
- no DEV5 integration target or frozen release ref changed.

READY_FOR_INTEGRATION: YES for the isolated DEV3 ACSDB/Library/Search/recovery/query-plan package; the PGN lost-update fix is exact-head GREEN on the same draft branch.
OVERALL_FULL_PRODUCT_DEV3: PARTIAL; additional dependency-correct task packages remain.
NEXT_ACTION: live-check ownership, then close the analogous no-overwrite final-publication TOCTOU in ACSDB backup/restore if still unclaimed; otherwise move to DEV3-owned training/progress analytics backend work.
NVDA_VERIFIED: NO
WINDOWS_CANDIDATE: NONE created by DEV3.
BLOCKER: none for this isolated slice; integration/release authority remains DEV5/Auditor.
