# DEV5_RUN_STATE

RUN_ID: 20260822-1659
STARTED_LOCAL: 16:59:45 Europe/Kyiv
STATUS: COMPLETE
MODE: SELECTIVE_FULL_PRODUCT_INTEGRATION_VALIDATION_GREEN
COORDINATION_BRANCH: manual5/dev5-regression-integration-20260821
VALIDATION_BRANCH: full5/dev5-compose-1700-20260822
VALIDATION_PR: #93 OPEN/DRAFT/DO_NOT_MERGE
PRIOR_GREEN_BRANCH: full5/dev5-selective-compose-20260822
PRIOR_GREEN_SHA: 7f4d2af3447d8d5046c9a75e1243a4ce36b11e4a
STAGE1_INTEGRATION_TARGET: manual5/integration-20260821
STAGE1_INTEGRATION_SHA: 0fa442330bc2bb03636ff9297512da4c29e38684
FINAL_SNAPSHOT_CUTOFF: 2026-08-22T16:59:45+03:00
ACTIVE_DIRECTIVE_AT_START: 0018
OBSERVED_NEXT_DIRECTIVE: 0019 effective 17:00 Europe/Kyiv
NVDA_VERIFIED: NO
FRESH_WINDOWS_CANDIDATE: NO
READY_FOR_RELEASE: NO

## Instruction discovery
AGENTS.md and shared docs/codex/CURRENT_STATE.md, NEXT_WORK.md and SESSION_HANDOFF.md remain absent on the inspected repository ref. Live GitHub, canonical Drive lane handoffs/RUN_STATE and docs/automation coordinator state govern this run.

## Snapshot ruling
No touching DEV1-DEV4 Product worker was IN_PROGRESS before the immutable 16:59:45 cutoff. DEV1 and DEV2 were terminal/no-mutation, DEV3 had terminalized its cumulative non-PGN package before cutoff, and DEV4 was terminal QA-only with Product source unchanged. SAFE OVERLAP therefore cleared for selective non-PGN validation composition only. Shared PGN/ChessBase/import remained blocked and was not touched.

## Accepted Stage1
manual5/integration-20260821 remains exact 0fa442330bc2bb03636ff9297512da4c29e38684. PR #54/frozen refs untouched. Rejected ZIP not reused. No Windows candidate.

## Prior GREEN baseline preserved
full5/dev5-selective-compose-20260822 remains preserved at exact 7f4d2af3447d8d5046c9a75e1243a4ce36b11e4a with prior exact CI 32569504104 / 97022845834 SUCCESS. PR #88 remains OPEN/DRAFT/DO NOT MERGE and was not mutated.

## DEV1 selected terminal delta
Canonical terminal cumulative source: full5/dev1-teacher-webview-20260822-1538 @ b873e18fe63e7fe9c01518627d33e4b6cc4f8646. Selective delta relative to already-composed DEV1 995f7846a56d7f52e6403544046da11e6d061c1c is Product/tests only:
- acs/full_product_webview_adapter.py
- acs/teacher_webview_projection.py
- tests/test_dev1_full_product_webview_adapter.py
- tests/test_dev1_teacher_webview_projection.py
DEV1 workflow metadata was excluded. One ActionRegistry/router, editable-control shortcut protection, route/dialog focus invariants, sanitized errors and atomic one-snapshot Teacher visual/NVDA projection are preserved.

## DEV2
Canonical full-product 4dd706838881c0e328c7578eada17227de43cf60 remains already represented from the prior GREEN baseline. No new DEV2 Product delta was needed. Canonical GameTree/BookDocument and CommentStyle.SEMICOLON semantics remain authoritative.

## DEV3 selected terminal delta
Fresh cutoff confirmed cumulative terminal non-PGN source auto/dev3-search-resource-bounds-20260822 @ 6f90516a8beefa8c191a8c593aaf3f2e410aa738. Selective Product/tests added relative to already-composed DEV3 51d77c4c6f6a70cd47ffb772fff476ce9480d135:
- acs/engine_assisted_workflows.py
- acs/student_progress.py
- acs/student_progress_store.py
- acs/search_service.py
- tests/test_dev3_engine_assisted_workflows.py
- tests/test_dev3_student_progress.py
- tests/test_dev3_student_progress_store.py
- tests/test_dev3_search_resource_bounds.py
DEV3 workflow/docs metadata and all PGN/external-import paths were excluded.

Accepted semantics include presentation-neutral engine assistance with stale/visibility suppression, append-only student review records without engine PV/score persistence, durable CAS progress storage with stale-writer/peer-lock fail-closed behavior, and normalized search terms bounded to 256 characters before SQLite execution.

## New selective composition
Atomic Product/test composition commit from exact prior GREEN base:
426e1489780f2d99932c417da89f2dae2015097b
Tree: 4faed44ed4ca88c5653005745c9cc7e93c3ca1d0
Exactly 12 selected Product/test paths were composed at this stage.

Validation branch: full5/dev5-compose-1700-20260822
DEV5 validation workflow was then scoped to this branch/base and expanded with the new focused suites.
Exact current source head: dd9ebf9414103c805892856fe6a04706fa69039f
Draft PR #93: OPEN / MERGEABLE / DRAFT / DO NOT MERGE
Base: exact prior GREEN 7f4d2af3447d8d5046c9a75e1243a4ce36b11e4a
Synthetic PR merge/evidence ref: 98d04a0463ff9712113c642fe8f4688f4da175e6

## Exact combined CI
Workflow: DEV5 Full Product Selective Composition CI
Run: 32577600761
Job: 97042099941
Source head associated with run: dd9ebf9414103c805892856fe6a04706fa69039f
PR merge/evidence checkout: 98d04a0463ff9712113c642fe8f4688f4da175e6 against exact base 7f4d2af3447d8d5046c9a75e1243a4ce36b11e4a
Conclusion: SUCCESS

Evidence:
- diff hygiene + compile PASS
- DEV1 WebView/presentation/accessibility focused: 111/111 PASS
- canonical GameTree/BookDocument: 22/22 PASS
- DEV3 data/progress/search/engine-assisted focused: 53/53 PASS
- full unittest discovery: 789/789 PASS
- full pytest: 867 PASS + 826 subtests PASS
- SELFTEST PASS
- ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS
No test was weakened, skipped or xfailed to obtain GREEN.

## DEV4 shared-boundary blocker
DEV4 Product source remains unchanged at a4209d005ea0a1476f8eafb4822f4d39ac50ee5a. No terminal Product repair was available before cutoff. Twelve locked PGN/ChessBase/import defect classes therefore remain outside this GREEN composition:
1. symlink/reparse import indirection;
2. unbounded PGN reads/source-size;
3. serialized local-path leakage;
4. expected_sha256 TOCTOU;
5. overwrite=False competing-creator race;
6. PGN export filesystem-indirection/symlink escape;
7. companion-directory I/O false absence;
8. inspect_batch importer RuntimeError abort;
9. manifest hash/open I/O propagation;
10. FIFO/device-like/non-regular pre-open;
11. unstable provenance hashing during same-size concurrent mutation across shared import and ChessBase integrity paths;
12. raw failed-import exception persistence/application exposure through ACSDB import history.

PGN/ChessBase/import readiness remains BLOCKED. This run makes no release claim for those paths.

## Product/release decision
The new source head dd9ebf9414103c805892856fe6a04706fa69039f is the current exact-GREEN DEV5 selective validation authority for the proved non-PGN scope. PR #93 remains validation evidence only and MUST NOT be merged wholesale. Stage1/release/frozen refs remain unchanged. Windows candidate remains absent and NVDA_VERIFIED remains NO.

## Next
1. Fresh cutoff at next invocation.
2. Preserve the new GREEN dd9ebf... baseline unless a concrete combined regression appears.
3. DEV4 remains highest priority: produce one terminal Product repair for all twelve shared PGN/ChessBase/import defect classes with deterministic regressions and observable exact-head CI.
4. Once terminal repair exists, DEV5 selectively layers only accepted shared-boundary fixes onto dd9ebf... lineage.
5. Run dedicated PGN -> canonical GameTree -> ACSDB -> Search/Open vertical covering malformed-input atomicity, bounded resources, no lost updates, batch continuation, path/error privacy, provenance stability, retry/recovery, special-file rejection, signed-64-bit SQLite bounds, keyboard/focus invariants, full unittest, full pytest and complete diagnostic.
6. Advance persistent shared-boundary authority only after that repaired vertical is exact GREEN.

READY_FOR_AUDITOR_READBACK=YES
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
