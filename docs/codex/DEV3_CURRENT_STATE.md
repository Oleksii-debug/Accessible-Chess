# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / performance safety.

Active branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft PR: #65 against `codex/full-product-20260821`

Latest verified package head before documentation-only synchronization: `6c7e9212584ccf6c567d3b9297b7104d73e8b6b1`
Exact CI run/job: `32527856952` / `96913668679` — SUCCESS.

Verified ACSDB / Library / Search package now includes:
- stable keyset paging for games, import attempts and exact-position `(game_id, ply)` results;
- source provenance on game and position result rows;
- schema v3 composite exact-position index;
- WAL + 5000 ms busy timeout for file-backed databases after supported-schema migration;
- strict no-coercion query cursor/limit contracts through ACSDB, GameSearchService and ImportHistoryService;
- deterministic 1,200-game paging with no duplicate ids;
- v2->v3 migration preservation;
- WAL reader/writer concurrency coverage;
- consistent SQLite backup via native backup API;
- `quick_check` + supported-schema validation before backup publication or restore;
- atomic peer-temp replacement for backup/restore;
- default overwrite protection, explicit exact-boolean overwrite contract;
- corrupt/future-schema backup fail-closed behavior with existing destination preserved.

Exact CI evidence on `6c7e9212...`:
- diff hygiene PASS;
- compile PASS;
- focused ACSDB/position/WAL/recovery suite: 31/31 PASS;
- full unittest discovery: 566/566 PASS;
- full pytest: 644 passed + 545 subtests passed;
- accepted Stage1 engine/play/analysis/clocks/lifecycle regressions remain GREEN in full discovery;
- no tests weakened/skipped for GREEN.

Stage1 engine package remains preserved and was not redone.

Readiness:
- Stage1 engine backend: COMPLETE / already accepted downstream; `NVDA_VERIFIED=NO`.
- Current Full Product ACSDB / Library / Search / recovery slice: `READY_FOR_INTEGRATION=YES`.
- Overall DEV3 Full Product mission: PARTIAL; next unclaimed work is bounded query-plan/performance review, then non-duplicative import/export and engine-assisted training/teacher analytics review.
- Frozen release refs untouched; DEV5/Auditor retain integration/release authority.
