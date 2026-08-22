# AUTO-CHESS DEV3 session handoff

UTC checkpoint: 2026-08-22T08:00Z.

Continued the same DEV3 Full Product work on `auto/dev3-acsdb-stable-paging-20260821` / draft PR #65. A fresh ownership read showed prior DEV3 work COMPLETE for its last slice and no touching DEV3 package IN_PROGRESS, so this run claimed a non-conflicting ACSDB / Library / Search P1. DEV2 canonical GameTree/domain, DEV1 presentation/UI and Teacher surfaces, DEV4 QA/security, and DEV5 integration/promotion remained untouched.

New package: deterministic literal text semantics for ACSDB / Library / Search.

Root defect:
- values were safely parameterized against SQL injection, but SQLite `LIKE` still interpreted user-entered `%` and `_` as wildcard operators;
- searches such as player `%` could therefore broaden to effectively every non-null player instead of searching for a literal percent sign;
- backslash also needed explicit escaping once an SQL `ESCAPE` character is introduced.

Implementation:
- `acs/search_service.py` now escapes `\\`, `%` and `_` before building LIKE parameters;
- player, event, ECO, opening and source-name filters use explicit `ESCAPE '\\'` clauses;
- normal case-insensitive substring semantics are preserved;
- ECO preserves its existing prefix semantics;
- no raw SQL fragments are exposed to callers and all values remain parameterized.

Tests / CI routing:
- `tests/test_search_service.py` now includes deterministic regressions for literal percent, underscore, backslash, mixed source names and ECO literal-prefix behavior;
- `.github/workflows/dev3-full-product-acsdb-ci.yml` now includes `tests.test_search_service` in the focused DEV3 suite;
- validation-only branch `auto/dev3-literal-search-ci-evidence-20260822` and draft PR #81 were created against the exact active DEV3 Product branch; DO NOT MERGE #81.

Exact implementation/test checkpoints:
- `0bf8dc2041421914948350fe48b0e3a03e9d65bd` — search implementation;
- `a3c93e319cc7c01126dd3a6dd8a3e945b9bf4032` — regressions;
- `753ba0ac27e37a944820b2917f2fd2518be283e5` — focused CI routing and executable Product checkpoint before handoff-only documentation commits.

Verification available in this runtime:
- independent SQLite semantic smoke for `%`, `_` and `\\`: PASS;
- local clone/test attempt: BLOCKED because the runtime container could not resolve `github.com`;
- PR #81 initial merge ref before later handoff-only Product docs: `1cf56c3ef57d5b9bddc3bb9e3e89347f5b649957`;
- connector had not yet returned a terminal applicable GitHub Actions run for the new final composition at this checkpoint.

Therefore:
- this new literal-search P1 is IMPLEMENTED but `CI_PENDING`;
- it is NOT YET CLAIMED GREEN and NOT YET READY_FOR_INTEGRATION;
- no test was weakened or skipped to obtain a result.

Last terminally verified DEV3 executable checkpoint remains `1ca5784b3ce00837b40888a26dd1e94d8ce754ed`, exact GREEN run/job `32558628088` / `96996629973`, merge ref `ff2fd2600e38b885a74f60fa1f61cf4956da1995`; evidence there was focused 78/78, full unittest 612/612, full pytest 690 passed + 585 subtests, diff/compile/diagnostic PASS.

Previous verified DEV3 ACSDB/Library/Search/recovery/query-plan, atomic publication, Training revision-bound + durable CAS progress and Books durable progress packages remain `READY_FOR_INTEGRATION=YES`.

Exact next action: re-read final Product branch head plus PR #65/#81, obtain the terminal Actions run/job/merge-ref and test counts for the final documentation-synchronized composition, inspect any RED log without weakening tests, and if GREEN close #81 unmerged and update all DEV3 coordination files to the exact verified head. Then claim the next unowned dependency-correct ACSDB/Library/Search or presentation-neutral Books/Training/progress backend P1.

Frozen Stage1 refs were not moved. No Windows candidate was created. Search/Linux evidence is not human screen-reader acceptance. `NVDA_VERIFIED=NO`.
