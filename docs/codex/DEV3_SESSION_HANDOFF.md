# AUTO-CHESS DEV3 session handoff

UTC checkpoint: 2026-08-22T08:06Z terminal executable verification completed.

Continued the same DEV3 Full Product work on `auto/dev3-acsdb-stable-paging-20260821` / draft PR #65. A fresh ownership read showed prior DEV3 work COMPLETE for its last slice and no touching DEV3 package IN_PROGRESS, so this run claimed a non-conflicting ACSDB / Library / Search P1. DEV2 canonical GameTree/domain, DEV1 presentation/UI and Teacher surfaces, DEV4 QA/security, and DEV5 integration/promotion remained untouched.

New package: deterministic literal text semantics for ACSDB / Library / Search.

Root defect:
- values were safely parameterized against SQL injection, but SQLite `LIKE` still interpreted user-entered `%` and `_` as wildcard operators;
- searches such as player `%` could broaden to effectively every non-null player instead of searching for a literal percent sign;
- backslash also needed explicit escaping once an SQL `ESCAPE` character is introduced.

Implementation:
- `acs/search_service.py` now escapes `\\`, `%` and `_` before building LIKE parameters;
- player, event, ECO, opening and source-name filters use explicit `ESCAPE '\\'` clauses;
- normal case-insensitive substring semantics are preserved;
- ECO preserves its existing prefix semantics;
- no raw SQL fragments are exposed to callers and all values remain parameterized.

Tests / CI routing:
- `tests/test_search_service.py` contains deterministic regressions for literal percent, underscore, backslash, mixed source names and ECO literal-prefix behavior;
- `.github/workflows/dev3-full-product-acsdb-ci.yml` includes `tests.test_search_service` in the focused DEV3 suite;
- validation-only PR #81 was superseded and closed unmerged;
- final validation-only branch `auto/dev3-literal-search-ci-evidence-v2-20260822` / PR #82 verified the exact documentation-synchronized Product base and must not be merged.

Exact implementation/test checkpoints:
- `0bf8dc2041421914948350fe48b0e3a03e9d65bd` — search implementation;
- `a3c93e319cc7c01126dd3a6dd8a3e945b9bf4032` — regressions;
- `753ba0ac27e37a944820b2917f2fd2518be283e5` — focused CI routing;
- latest verified executable Product head `85b88d2efd8fb92f0be5500e5a8da2b86228e46a` includes the synchronized pre-validation DEV3 handoff state.

Terminal GitHub Actions evidence:
- workflow: `DEV3 Full Product ACSDB CI`;
- run `32561369567`, run number 169 — SUCCESS;
- job `97003308118` (`acsdb`) — SUCCESS;
- workflow merge ref `d075bc872f40af64a3470fd5d4e869574a8a866a` = Product head `85b88d2...` plus evidence-only marker `fc41342087b2be2b82d318eaa090658c8c11b7b8`;
- GitHub runner 2.336.0; Ubuntu 24.04.4 image 20260816.277.1; Python 3.12.14;
- diff hygiene PASS;
- compileall including launcher PASS;
- focused DEV3 data/Books/Training/Search suite 85/85 PASS;
- both new literal-search regressions PASS;
- full unittest 614/614 PASS;
- full pytest 692 passed + 585 subtests PASS;
- SELFTEST PASS;
- ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS;
- no test was weakened or skipped.

Decision:
- literal ACSDB/Library/Search correctness P1 is COMPLETE and exact executable-head GREEN;
- DEV3 ACSDB/Library/Search/recovery/query-plan + literal-search package is `READY_FOR_INTEGRATION=YES`;
- Training revision-bound snapshot + durable CAS persistence and Books durable reading-progress integrity slices remain COMPLETE / GREEN;
- overall DEV3 Full Product mission remains PARTIAL;
- next action after a fresh live ownership check: another unclaimed dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1; remain SAFE OVERLAP if touching work is owned;
- Node20-target Actions deprecation warning while runner forces Node24 remains non-blocking P2 hygiene only;
- fresh Windows candidate: NONE;
- Linux/search/accessibility contract CI is not personal NVDA evidence;
- `NVDA_VERIFIED=NO`;
- DEV5/Auditor retain integration/release authority.
