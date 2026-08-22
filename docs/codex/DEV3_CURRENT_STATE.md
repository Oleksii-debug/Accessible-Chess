# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Books/Training progress backend contracts.

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest verified executable Product head: `99b5c61c31585d7b2474a050eeb006bf639943dd`.
Exact GREEN CI run/job: `32550533728` / `96976421604`.
Workflow PR merge ref: `c134100d797d5436ec3f7ff4a6aa4d7a84f3cdf9` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

New P1 delivered in this continuation: BookReader index-fallback revision integrity.
- BookReader already persisted durable semantic targets using `block_id`, then `source_anchor`, but blocks lacking both identifiers fell back to `index:N`.
- Those index targets were described as snapshot-local yet were accepted by durable restore without any revision identity, so an insertion or semantic edit at the same numeric index could silently restore progress onto a different block.
- `BOOK_READER_SNAPSHOT_SCHEMA_VERSION = 2` now adds strict `fallback_digests` only for referenced `index:*` targets.
- Each fallback digest is lowercase SHA-256 over canonical JSON of the semantic block payload returned by `block.as_dict()`; stable `block:*` and `source:*` targets are unchanged and remain reorder-safe without a digest.
- Restore requires the digest key set to exactly match referenced index fallbacks, rejects malformed/coercive digests, resolves every target, and then fails closed if the block currently occupying an index fallback no longer has the same semantic payload.
- Exact same-revision index-only snapshots still round-trip. Insertion before the target and semantic edits at the same index are now rejected instead of drifting.
- Schema v1 is rejected by the strict restore boundary; any persistence migration must be explicit rather than guessed.
- No chess legality, GameTree, board, UI, keybinding, Windows or NVDA presentation authority was introduced.
- Dedicated BookReader progress regression file now contains 12 tests.

Exact CI evidence on `99b5c61c...` through merge ref `c134100d...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite: 65/65 PASS;
- full unittest discovery: 599/599 PASS;
- full pytest: 677 passed + 581 subtests passed;
- all 12 BookReader progress-contract regressions PASS;
- no tests weakened or skipped for GREEN.

Previously verified DEV3 packages remain intact: ACSDB stable keyset paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan, PGN and ACSDB atomic no-overwrite publication, Training revision-bound snapshots, and stable BookReader semantic-target progress.

SAFE OVERLAP ownership remains:
- DEV2 owns canonical GameTree/domain work.
- DEV1 owns presentation/UI and Teacher presentation surfaces.
- DEV4 owns independent QA/security findings.
- DEV5 owns cross-lane integration/promotion.

Readiness:
- DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
- Training revision-bound snapshot slice: COMPLETE / GREEN.
- Books durable reading-progress + index-fallback revision-integrity slice: COMPLETE / GREEN.
- Overall DEV3 Full Product mission: PARTIAL.
- Next action: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; stay SAFE OVERLAP on touching owned work.
- Frozen Stage1 release refs untouched. No Windows candidate created. `NVDA_VERIFIED=NO`.
