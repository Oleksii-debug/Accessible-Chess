# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export storage safety.

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest verified executable package head before documentation-only synchronization: `7c1c0b8092fc487e49d9a654f0f847f6035bedb1`.
Exact CI run/job: `32535629207` / `96935870586` — SUCCESS.
PR merge ref executed by the workflow: `acdc7e8754d150e3ddce367f9ba02831f4e5a7ce` against Full Product base `656e8ec311e364e6e54a30504fd30a4aaff586f9`.
Runner evidence: GitHub runner `2.336.0`, `ubuntu-24.04@20260816.277.1`, Python 3.12.14.

Verified DEV3 package now includes the prior ACSDB / Library / Search package plus the PGN file-publication lost-update closure:
- stable keyset paging for games, import attempts and exact-position `(game_id, ply)` results;
- source provenance on game and position result rows;
- schema v3 composite exact-position index;
- WAL + 5000 ms busy timeout for file-backed databases after supported-schema migration;
- strict no-coercion query cursor/limit contracts through ACSDB, GameSearchService and ImportHistoryService;
- deterministic large-dataset paging with no duplicate ids;
- v2->v3 migration preservation and WAL reader/writer concurrency coverage;
- consistent SQLite backup via native backup API, integrity validation and atomic peer-temp publication;
- query-plan evidence over large deterministic datasets and the 1,000-row public search bound;
- `PgnFileService` no longer uses unconditional `os.replace()` for `overwrite=False`: a same-directory atomic create-if-absent publication prevents a concurrent creator from being silently clobbered;
- `PgnFileService.overwrite` now requires an exact boolean, consistent with other DEV3 storage/query scalar boundaries;
- deterministic regression proves a concurrent creator wins without lost data and temporary PGN files are cleaned up.

Exact CI evidence on `7c1c0b8...`:
- diff hygiene PASS;
- compileall PASS;
- focused ACSDB/position/WAL/recovery/query-plan suite: 36/36 PASS;
- full unittest discovery: 573/573 PASS;
- full pytest: 651 passed + 545 subtests passed;
- both new PGN regressions PASS;
- no tests weakened/skipped for GREEN.

Live ownership / SAFE OVERLAP:
- DEV2 remains owner of canonical GameTree/domain work; no GameTree/chess-rule source changed here.
- DEV1 owns presentation/UI and Teacher presentation surfaces.
- DEV4 QA PR #67 independently owns symlink/reparse, unbounded-PGN-resource and ChessBase report-path security findings; this DEV3 patch does not claim or alter those security findings.
- DEV5 owns cross-lane integration/promotion.

Readiness:
- Stage1 engine backend: COMPLETE / already accepted downstream; `NVDA_VERIFIED=NO`.
- DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
- PGN no-overwrite lost-update slice: COMPLETE / exact-head GREEN.
- Overall DEV3 Full Product mission: PARTIAL.
- Next unclaimed P1: inspect and close the analogous final publication race in ACSDB `backup_to()` / `restore_backup()` if it remains unclaimed: a last existence recheck followed by `os.replace()` can still race with a creator when `overwrite=False`. Preserve validated backup semantics and add deterministic race tests. If ownership changes before the next run, stay SAFE OVERLAP and move to DEV3 backend training/progress work instead.
- Frozen release refs untouched; no Windows candidate created; DEV5/Auditor retain integration/release authority.
