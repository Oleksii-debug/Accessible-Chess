# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Books/Training progress backend contracts.

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest verified executable Product head: `c85a489cde459831990d67a717c8e6bf47ad9dd2`.
Exact GREEN CI run/job: `32547927505` / `96969673770`.
Workflow PR merge ref: `ae65bcdf838ccd1e438f7db1acbad161cdfd25b1` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

New P1 delivered in this continuation: Training snapshot revision integrity.
- Training progress had been bound only to `exercise_id` plus numeric progress. Reusing the same stable ID after changing the start position or ordered solution could silently restore stale progress into a different semantic exercise revision.
- `TRAINING_SNAPSHOT_SCHEMA_VERSION = 2` now carries a strict `definition_digest`.
- The digest is SHA-256 over presentation-neutral exercise semantics only: normalized `start_fen` plus the ordered accepted-move sets for every step.
- Presentation-only edits such as title, tags, source metadata, hints and explanations intentionally do not invalidate compatible progress.
- restore rejects malformed/coercive digests, changed start positions, changed solution moves and reordered steps even when `exercise_id` is unchanged.
- schema v1 fails closed because it has no revision identity; any migration must be explicit at the persistence-adapter boundary rather than guessed.
- no chess legality, GameTree, board, UI, keybinding or presentation authority was introduced; Training continues to treat move/FEN semantics as core-owned opaque facts.
- dedicated revision-bound snapshot regression file now contains 12 tests.

Exact CI evidence on `c85a489c...` through merge ref `ae65bcdf...`:
- diff hygiene PASS;
- compileall PASS;
- focused DEV3 data/reading-progress suite: 61/61 PASS;
- full unittest discovery: 595/595 PASS;
- full pytest: 673 passed + 574 subtests passed;
- all 12 Training snapshot revision-integrity regressions PASS;
- no tests weakened or skipped for GREEN.

Previously verified DEV3 packages remain intact: ACSDB stable keyset paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan, PGN and ACSDB atomic no-overwrite publication, and BookReader durable semantic reading-progress.

SAFE OVERLAP ownership remains:
- DEV2 owns canonical GameTree/domain work.
- DEV1 owns presentation/UI and Teacher presentation surfaces.
- DEV4 owns independent QA/security findings.
- DEV5 owns cross-lane integration/promotion.

Readiness:
- DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
- Training revision-bound snapshot slice: COMPLETE / GREEN.
- Books durable reading-progress slice: COMPLETE / GREEN.
- Overall DEV3 Full Product mission: PARTIAL.
- Next action: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; stay SAFE OVERLAP on touching owned work.
- Frozen Stage1 release refs untouched. No Windows candidate created. `NVDA_VERIFIED=NO`.
