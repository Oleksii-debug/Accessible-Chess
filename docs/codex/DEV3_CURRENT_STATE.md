# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Books/Training progress backend contracts.

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest verified executable Product head: `7e0d933b1fa6b48318d09683757bb1a54f44ef75`.
Exact GREEN CI run/job: `32545080795` / `96962002799`.
Workflow PR merge ref: `6a1538bcac605f33cc22888ea0045a2324506faa` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

New P1 delivered in this continuation: durable semantic BookReader reading-progress exchange.
- BookReader return points no longer persist raw block indices that can silently drift after source-preserving book edits/reordering.
- Reader progress now reuses the existing `BookIndex` semantic target authority: `block_id` first, `source_anchor` second, index-only fallback only when no durable source identity exists.
- `BOOK_READER_SNAPSHOT_SCHEMA_VERSION = 1` defines an exact versioned snapshot with `current_target` and named `return_points`.
- restore rejects missing/unknown fields, unsupported versions and coercive scalar/container shapes.
- deleted semantic targets fail explicitly; duplicate/ambiguous identities fail closed through `BookIndex.resolve` rather than selecting an arbitrary block.
- current location and named return points survive source-preserving reorder when durable block/source identities remain available.
- no chess legality, GameTree, board, UI, keybinding or presentation authority was introduced.
- dedicated regression file: `tests/test_dev3_bookreader_progress_contract.py` (8 tests).

Exact CI evidence on `7e0d933...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite: 56/56 PASS;
- full unittest discovery: 590/590 PASS;
- full pytest: 668 passed + 567 subtests passed;
- all 8 new BookReader progress regressions PASS;
- no tests weakened or skipped for GREEN.

Previously verified DEV3 packages remain intact: ACSDB stable keyset paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan, PGN and ACSDB atomic no-overwrite publication, and strict Training snapshot schema-v1 persistence contracts.

SAFE OVERLAP ownership remains:
- DEV2 owns canonical GameTree/domain work.
- DEV1 owns presentation/UI and Teacher presentation surfaces.
- DEV4 owns independent QA/security findings.
- DEV5 owns cross-lane integration/promotion.

Readiness:
- DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
- Training strict snapshot-contract slice: COMPLETE / GREEN.
- Books durable reading-progress slice: COMPLETE / GREEN.
- Overall DEV3 Full Product mission: PARTIAL.
- Next action: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; stay SAFE OVERLAP on touching owned work.
- Frozen Stage1 release refs untouched. No Windows candidate created. `NVDA_VERIFIED=NO`.
