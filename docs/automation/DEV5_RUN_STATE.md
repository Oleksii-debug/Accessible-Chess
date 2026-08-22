# DEV5_RUN_STATE

RUN_ID: 20260822-1347
STARTED_LOCAL: 13:41 Europe/Kyiv
STATUS: COMPLETE
MODE: SAFE_OVERLAP_COORDINATION
COORDINATION_BRANCH: manual5/dev5-regression-integration-20260821
STAGE1_INTEGRATION_TARGET: manual5/integration-20260821
STAGE1_INTEGRATION_SHA: 0fa442330bc2bb03636ff9297512da4c29e38684
FINAL_SNAPSHOT_CUTOFF: 2026-08-22T13:47:55+03:00
DIRECTIVE_SNAPSHOT: NEXT_WAVE_DIRECTIVES 0014 effective 13:00; 0015 observed but future-effective at 14:00 and deliberately not overwritten
NVDA_VERIFIED: NO
FRESH_WINDOWS_CANDIDATE: NO
STAGE_2: BLOCKED

## Stage1 exact state
manual5/integration-20260821 remains exact 0fa442330bc2bb03636ff9297512da4c29e38684. Exact observable gates remain GREEN: Stage1 Saturation run 32532577641 SUCCESS and UI Semantic run 32532577650 SUCCESS; prior pair 32532503262 / 32532503184 also SUCCESS. No Stage1 Product mutation. PR #54/frozen refs untouched; rejected ZIP not reused; no Windows candidate.

## DEV1 touching-lane snapshot — actively moving / non-terminal
Canonical Drive DEV1_RUN_STATE RUN_ID 20260822-0041 still says STATUS=IN_PROGRESS and canonical 10_DEV1_HANDOFF_CURRENT remains stale/non-terminal for this full-product continuation. During this DEV5 run PR #68 moved twice: c1425c898b3b6d1a4caea6a57a71544ee8582909 -> 0249f05d9345e8cb1e4063311327a6ff6388aaa1 -> final observed cutoff head 415eea75735c0de727d3f082c5c4dfeaf846b0a3. Current exact changed paths are:
- .github/workflows/dev1-full-product-ui-ci.yml
- acs/full_product_actions.py
- acs/full_product_presenters.py
- acs/full_product_ui_shell.py
- acs/teacher_presentation.py
- tests/test_dev1_full_product_accessible_shell.py
- tests/test_dev1_full_product_ui_packages.py
The branch now includes a dedicated DEV1 Full Product UI CI workflow plus accessible action routing and PGN/Library/Book/Training presenters over canonical services. Exact pull-request run lookup is empty because this new workflow is push/dispatch scoped, and combined legacy status is also empty; no exact GREEN is claimed here.

SAFE OVERLAP remains mandatory: this is live evidence of active DEV1 mutation, not a stale abandoned marker. DEV5 performs no competing full-product Product push.

## Preliminary DEV1-to-canonical API compatibility readback
Accepted Stage1 keybindings at 0fa44233 expose BindingContext.DATABASE and BindingContext.BOOK_READER, matching DEV1 full_product_actions.py. DEV3 exact 3dde3a... exposes the imported GameSearchQuery/GameSearchPage/GameSearchItem/GameSearchService, BookReader/ReadingLocation and ExerciseSession/ExerciseResult/ExerciseStatus/HintResult contracts used by DEV1 presenters. DEV2 exact 4dd706... exposes PgnGame/VariationLine/MoveNode shapes used by PgnTreePresenter (tags, line, warnings, result, SAN, comments, NAGs, nested variations). No immediate named-API mismatch is proven by static readback. This is NOT substitute for exact combined runtime CI.

## DEV2 terminal exact package
DEV2_RUN_STATE 20260822-1238 COMPLETE. Canonical Product head 4dd706838881c0e328c7578eada17227de43cf60. Validation PR #83 head 7822926f82354d86f03592c40fcafb2faf9342df; exact DEV2 Full Product Core CI run 32565884179 / job 97014330560 SUCCESS. Snapshot 21/21, navigation 8/8, editing 8/8, insertion 6/6, annotations 8/8, legality 6/6, result/exchange 8/8, GameTree 14/14, export 7/7 PASS; unittest 742 OK + 1 SKIP; pytest 822 PASS + 1 SKIP + 1330 subtests. FULL_PRODUCT_DEV2_READY_FOR_INTEGRATION=YES. PR #83 evidence-only.

Selective-lineage proof: reusable Work head 6fa705f7ca80ee69b4183f99c9bc1c5a86048e64 vs DEV2 4dd706... has merge-base 0cf4fe291ff6c349de99978cd2fc68866a218da8. Meaningful post-Work DEV2 delta is clean GameTree/BookDocument domain modules/tests plus DEV2-only workflow; do not merge cumulative PR #69 history wholesale.

## DEV3 exact technical package
Executable Product checkpoint remains 3dde3a7444c9cf594e92e32f5e084c8969015ad4. Live PR #65 head 23aba247aa47bc2f7aa7051798e1b9c1b84a3621 is ahead only in docs/codex state files; Product did not move. Validation PR #84 CLOSED UNMERGED. Exact GREEN evidence remains run 32563847332 / job 97009443566 on merge ref f1134af309c3fe687b039f2aea5c0068b353408c: focused 87/87; unittest 616/616; pytest 694 + 585 subtests; SELFTEST and complete WebView2 diagnostic PASS.
DEV3 3dde3a... diverges from reusable Work 6fa705... at merge-base e8cd992d306975955784118364ce950963133d7e. Only selective exact data/backend intake is safe.

## DEV4 13:00 QA
DEV4_RUN_STATE 20260822-1300-full-product-qa COMPLETE at QA head 5d43b944b3fce7a798f2d002d691591ff9702fcd; PR #67 OPEN/DRAFT/MERGEABLE. Exact-head Actions NONE OBSERVED => INCONCLUSIVE, NOT GREEN. Product code unchanged.
Ten locked Product defects: symlink/reparse import indirection; unbounded PGN read/source size; ChessBase absolute-path serialization; expected_sha256 TOCTOU; overwrite=False creator race; PGN export indirection; companion-directory I/O misclassification; ImportRegistry.inspect_batch RuntimeError abort; manifest verification incidental I/O propagation; shared fingerprint opening FIFO/device-like special files before regular-file validation.

## Cross-plane lineage / rewrite-risk
Reusable full-product Work 6fa705... and accepted Stage1 0fa44233... diverge at e8cd992d.... Correct future assembly is selective: accepted Stage1 semantics + terminal DEV1 full-product presentation/action package + clean DEV2 GameTree delta + selected exact DEV3 data/backend delta + repaired DEV4 boundaries. Evidence PRs never become integration authority.

## Product action
NONE. SAFE OVERLAP only. No persistent full5 integration ref moved; no Product cherry-pick/merge/push; no Windows strict changes.

## Readiness estimates
Stage1 machine integration gates GREEN; last independent overall estimate about 93%, still blocked by fresh Windows release chain and human NVDA. Full-product integrated end-user readiness conservatively ~20-25%. GameTree/domain ~70-75%; ACSDB/Library/Search ~65-70%; full-product UI/Teacher foundation ~25-30% but actively moving/non-terminal; PGN/ChessBase ~25-30% with ten defects; Books/Training ~30-35%; Classroom/Lessons/Assignments/Remote ~10%.

## Next actions
1. DEV1 terminalize current moving full-product package at one exact Product SHA, synchronize DEV1_RUN_STATE + 10_DEV1_HANDOFF_CURRENT and publish observable exact CI evidence.
2. Close DEV4 ten locked PGN/ChessBase/import defects with strict regressions.
3. After SAFE OVERLAP clears, DEV5 builds validation-only selective composition and runs PGN -> GameTree -> ACSDB -> search/open malformed-input/resource/concurrency/path-privacy/retry/SQLite-range/keyboard-focus/full-regression matrix before any persistent full5 integration moves.

READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
