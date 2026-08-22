# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Books/Training progress backend contracts.

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest verified executable Product head: `86a2e6de3e1d89b939d31b6b5aa6de8100505c23`.
Exact GREEN CI run/job: `32553387781` / `96983670899`.
Workflow PR merge ref: `89cd9cb4ee7b140bb1924e58f9b10aed3b7a5ad2` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

New P1 delivered in this continuation: BookReader ambiguous durable-target write integrity.
- `BookIndex` deliberately permits duplicate semantic identifiers so imperfect source material can be inspected, while `resolve()` rejects ambiguity.
- Before this patch, `BookReader.save_return_point()` and `snapshot()` could still serialize a duplicate `block:*` or `source:*` key and only discover the ambiguity during a later restore.
- Durable progress now validates unique resolvability before a return point is mutated or a snapshot is published.
- Failed return-point save is atomic; a rejected ambiguous target does not remain in persisted progress state.
- Snapshot publication also preflights all referenced return points, preventing a non-restorable durable payload from being emitted.
- Four deterministic regressions cover duplicate block IDs, duplicate source anchors, atomic failed saves, and unchanged unique-target round trips.
- Existing BookReader schema-v2 `fallback_digests`, Training revision-bound snapshots, and ACSDB/Library/Search contracts remain intact.
- No chess legality, GameTree, board, UI, keybinding, Windows or NVDA presentation authority was introduced.

Exact CI evidence on `86a2e6de...` through merge ref `89cd9cb4...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite: 69/69 PASS;
- full unittest discovery: 603/603 PASS;
- full pytest: 681 passed + 581 subtests passed;
- all 4 new ambiguous-persistence regressions PASS;
- no tests weakened or skipped for GREEN.

Previously verified DEV3 packages remain intact: ACSDB stable keyset paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan, PGN and ACSDB atomic no-overwrite publication, Training revision-bound snapshots, BookReader semantic-target progress, and index-fallback revision integrity.

SAFE OVERLAP ownership remains:
- DEV2 owns canonical GameTree/domain work.
- DEV1 owns presentation/UI and Teacher presentation surfaces.
- DEV4 owns independent QA/security findings.
- DEV5 owns cross-lane integration/promotion.

Readiness:
- DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
- Training revision-bound snapshot slice: COMPLETE / GREEN.
- Books durable reading-progress integrity slices: COMPLETE / GREEN.
- Overall DEV3 Full Product mission: PARTIAL.
- Next action: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; stay SAFE OVERLAP on touching owned work.
- Frozen Stage1 release refs untouched. No Windows candidate created. `NVDA_VERIFIED=NO`.
