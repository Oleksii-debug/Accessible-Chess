# AUTO-CHESS DEV3 run state

STATUS: COMPLETE FOR LITERAL ACSDB/LIBRARY/SEARCH P1 / FULL PRODUCT MISSION PARTIAL
BRANCH: `auto/dev3-acsdb-stable-paging-20260821`
PRODUCT PR: #65
VALIDATION PR: #82 — EVIDENCE ONLY / DO NOT MERGE
DIRECTIVE: Full Product DEV3 / engine-analysis + ACSDB-Library-Search-import-export safety + presentation-neutral Books/Training progress backend contracts

Latest verified executable Product head: `85b88d2efd8fb92f0be5500e5a8da2b86228e46a`.
Exact GREEN CI run: `32561369567`.
Exact CI job: `97003308118`.
Workflow PR merge ref executed: `d075bc872f40af64a3470fd5d4e869574a8a866a` = exact Product head plus evidence-only marker `fc41342087b2be2b82d318eaa090658c8c11b7b8`.
Runner: GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14.

P1 delivered:
- user-entered `%`, `_` and `\\` are now literal ACSDB search text rather than implicit SQLite wildcard operators;
- explicit `ESCAPE '\\'` clauses cover player, event, ECO, opening and source-name filters;
- normal case-insensitive substring behavior remains intact; ECO remains a prefix filter;
- SQL values remain parameterized;
- deterministic tests cover percent, underscore, backslash, mixed source names and ECO literal-prefix behavior;
- no second chess rules, legality, GameTree, board, UI, keybinding or presentation authority was introduced.

Executable evidence on `85b88d2...` through merge ref `d075bc8...`:
- diff hygiene PASS;
- compileall including launcher PASS;
- focused DEV3 data/Books/Training/Search suite 85/85 PASS;
- both new literal-search regressions PASS;
- full unittest 614/614 PASS;
- full pytest 692 passed + 585 subtests PASS;
- `python run_accessible_chess.py --diagnostic`: SELFTEST PASS and complete WebView2 user-flow diagnostic PASS;
- no tests weakened/skipped for GREEN.

SAFE OVERLAP:
- DEV2 canonical GameTree/domain untouched;
- DEV1 presentation/UI/Teacher surfaces untouched;
- DEV4 QA/security ownership untouched;
- DEV5 integration target/promotion ownership untouched.

READY_FOR_INTEGRATION: YES for the isolated DEV3 ACSDB/Library/Search/recovery/query-plan + literal-search package, Training revision-bound snapshot + durable CAS persistence slices, and Books durable reading-progress integrity slices.
OVERALL_FULL_PRODUCT_DEV3: PARTIAL.
NEXT_ACTION: fresh ownership check, then another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1. P2 only when no higher-value P1 remains: Actions currently emit a non-blocking Node20-target deprecation warning while GitHub forces Node24.
NVDA_VERIFIED: NO
WINDOWS_CANDIDATE: NONE created by DEV3.
BLOCKER: none for this isolated slice; integration/release authority remains DEV5/Auditor.
