# AUTO-CHESS DEV3 current state

Lane: Full Product engine/analysis + ACSDB / Library / Search / import-export safety + presentation-neutral Books/Training progress backend contracts.

Active Product branch: `auto/dev3-acsdb-stable-paging-20260821`
Draft Product PR: #65 against `codex/full-product-20260821`
Terminal validation-only PR: #82 against the exact DEV3 Product branch; DO NOT MERGE.

Latest verified executable Product head: `85b88d2efd8fb92f0be5500e5a8da2b86228e46a`.
Exact GREEN CI run/job: `32561369567` / `97003308118`.
Workflow PR merge ref: `d075bc872f40af64a3470fd5d4e869574a8a866a` = exact Product head plus the documentation-only evidence marker `fc41342087b2be2b82d318eaa090658c8c11b7b8`.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

New P1 delivered in this continuation: deterministic literal text semantics for ACSDB / Library / Search.
- Search values were already parameterized against SQL injection, but SQLite `LIKE` still interpreted user-entered `%` and `_` as wildcard operators.
- `GameSearchService` now escapes `\\`, `%` and `_` and uses an explicit SQLite `ESCAPE '\\'` clause for player, event, ECO, opening and source-name filters.
- Existing case-insensitive substring behavior remains unchanged for player/event/opening/source-name; ECO remains a prefix filter.
- User metacharacters are literal search text rather than implicit wildcard operators.
- Deterministic regressions cover literal percent, underscore, backslash, mixed source-name text and ECO literal-prefix behavior.
- `tests.test_search_service` is part of the focused Full Product DEV3 CI suite.
- No chess legality, canonical GameTree, board, UI, keybinding, Windows or NVDA presentation authority was introduced or modified.

Exact executable evidence on `85b88d2...` through merge ref `d075bc8...`:
- diff hygiene PASS;
- compileall including `run_accessible_chess.py` PASS;
- focused DEV3 data/Books/Training/Search suite: 85/85 PASS;
- both new literal-search regressions PASS;
- full unittest discovery: 614/614 PASS;
- full pytest: 692 passed + 585 subtests passed;
- complete diagnostic: SELFTEST PASS and ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS;
- no tests weakened or skipped for GREEN.

Previously verified DEV3 packages remain intact: ACSDB stable keyset paging/provenance/schema-v3/WAL/strict scalars/backup-recovery/query-plan, PGN and ACSDB atomic no-overwrite publication, Training schema-v2 revision-bound snapshots + durable CAS persistence, and BookReader durable semantic progress integrity.

SAFE OVERLAP ownership remains:
- DEV2 owns canonical GameTree/domain work.
- DEV1 owns presentation/UI and Teacher presentation surfaces.
- DEV4 owns independent QA/security findings.
- DEV5 owns cross-lane integration/promotion.

Readiness:
- DEV3 ACSDB/Library/Search/recovery/query-plan package: `READY_FOR_INTEGRATION=YES`.
- Literal-search correctness P1: `GREEN / READY_FOR_INTEGRATION=YES`.
- Training revision-bound snapshot + durable CAS progress slices: COMPLETE / GREEN.
- Books durable reading-progress integrity slices: COMPLETE / GREEN.
- Overall DEV3 Full Product mission: PARTIAL.
- Next action: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; stay SAFE OVERLAP on touching owned work.
- Non-blocking P2 hygiene remains: GitHub warns that actions target deprecated Node20 while the runner forces Node24.

Frozen Stage1 release refs untouched. No Windows candidate created. Linux/search CI is not personal NVDA verification. `NVDA_VERIFIED=NO`.
