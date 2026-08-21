# AUTO-CHESS DEV3 run state

STATUS: COMPLETE FOR QUERY-PLAN / LARGE-DATASET EVIDENCE SLICE / FULL PRODUCT MISSION PARTIAL
BRANCH: `auto/dev3-acsdb-stable-paging-20260821`
PR: #65
DIRECTIVE: Full Product DEV3 / engine-analysis + ACSDB-Library-Search-performance

Latest verified executable package head before documentation synchronization: `3f6fd2ff336eab4d0c8b9863da792f1c3d3e28f3`.
Exact CI run: `32531622900`.
Exact CI job: `96924650174` — SUCCESS.
The PR workflow checked out merge ref `d9678a23e31b1bcb304d56f10e72e6fe70c8a215` for head `3f6fd2ff...` against frozen Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.

This continuation stayed in SAFE OVERLAP MODE and did not modify Product source. It added deterministic evidence for the next unclaimed P1 package:
- actual public ACSDB SELECT statements are captured and checked with SQLite `EXPLAIN QUERY PLAN`;
- 5,000-game keyset traversal is deterministic, complete and duplicate-free;
- public game search remains hard-bounded to 1,000 rows even when a larger limit is requested;
- unfiltered keyset search streams through the INTEGER PRIMARY KEY cursor without a temporary sort;
- exact `result` and `source_id` filters use the existing `idx_games_result` / `idx_games_source` indexes and avoid `USE TEMP B-TREE`;
- ECO prefix search preserves deterministic `g.id` streaming order without a temporary sort; no unsupported claim is made that leading-wildcard text searches are index-backed;
- import-attempt status/SHA keyset filters use their existing indexes without temporary sorting;
- exact-position paging uses `idx_positions_key_game_ply` and preserves stable `(game_id, ply)` order.

Exact executable evidence on `3f6fd2ff...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 ACSDB suite: 36/36 PASS;
- full unittest discovery: 571/571 PASS;
- full pytest: 649 passed + 545 subtests passed;
- no weakened or skipped tests for GREEN.

READY_FOR_INTEGRATION: YES for the isolated DEV3 ACSDB/Library/Search/recovery package including this evidence gate.
OVERALL_FULL_PRODUCT_DEV3: PARTIAL; additional dependency-correct task packages remain.
NVDA_VERIFIED: NO
WINDOWS_CANDIDATE: NONE created by DEV3.
BLOCKER: none for this isolated slice; integration/release authority remains DEV5/Auditor.
