# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Books/Training progress backend contracts.

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest verified executable Product head: `feaa097bb9c87667132fcede7c0d192503b1d7b9`.
Exact GREEN CI run/job: `32556145719` / `96990471833`.
Workflow PR merge ref: `4147f3cee7277db773f1cac16a87fd1b7cf63950` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

New P1 delivered in this continuation: BookReader live-document mutation guard for durable progress.
- `BookIndex` is an immutable semantic index built from one `BookDocument` snapshot, while the source document remains authoring-mutable.
- Before this patch, in-place block reorder/insert or semantic identity edits could leave `save_return_point()`, `restore_return_point()` and `snapshot()` consulting stale index entries.
- The reader now stores a SHA-256 semantic revision fingerprint for the indexed blocks and fails closed before durable target work whenever the live document differs.
- Durable progress saved before an edit can still be restored into a fresh reader after a source-preserving reorder when stable semantic identity remains valid.
- Four deterministic regressions cover reorder, identity edit, insertion and correct fresh-reader restore after edit.
- Existing schema-v2 fallback digests, ambiguous-target preflight, Training revision-bound snapshots and ACSDB/Library/Search contracts remain intact.
- No chess legality, GameTree, board, UI, keybinding, Windows or NVDA presentation authority was introduced.

Exact CI evidence on `feaa097b...` through merge ref `4147f3c...`:
- diff hygiene PASS;
- compileall including `run_accessible_chess.py` PASS;
- focused DEV3 data/reading-progress suite: 73/73 PASS;
- full unittest discovery: 607/607 PASS;
- full pytest: 685 passed + 581 subtests passed;
- complete diagnostic: SELFTEST PASS and ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS;
- no tests weakened or skipped for GREEN.

Previously verified DEV3 packages remain intact: ACSDB stable keyset paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan, PGN and ACSDB atomic no-overwrite publication, Training revision-bound snapshots, BookReader semantic-target progress, index-fallback revision integrity and ambiguous durable-target write integrity.

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
